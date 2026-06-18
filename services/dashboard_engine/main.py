import os
import sys
import json
import subprocess
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import redis.asyncio as aioredis

# Aggiungi la root del progetto al path per importare core
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.database import DatabaseManager

class SettingRequest(BaseModel):
    key: str
    value: str

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

background_tasks = set()

app = FastAPI(title="Mission Control Dashboard")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
db = DatabaseManager()

# Lista di tutti i client WebSocket connessi
connected_clients = set()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/settings")
async def get_settings():
    """Recupera le impostazioni correnti da Redis."""
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        keys = await r.keys("config:*")
        settings = {}
        if keys:
            values = await r.mget(keys)
            for k, v in zip(keys, values):
                clean_key = k.replace("config:", "")
                settings[clean_key] = v
        await r.close()
        return {"status": "success", "settings": settings}
    except Exception as e:
        logger.error(f"Errore lettura settings da Redis: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/settings")
async def update_setting(req: SettingRequest):
    """Aggiorna un'impostazione sia nel DB che in Redis."""
    logger.info(f"Ricevuta richiesta modifica {req.key} a {req.value}")
    try:
        # 1. Salva su DB (Permanent Storage)
        # Esegui in un thread separato dato che DB è sincrono
        await asyncio.to_thread(db.update_setting, req.key, req.value)
        
        # 2. Salva su Redis (Fast Cache)
        r = aioredis.from_url(REDIS_URL)
        await r.set(f"config:{req.key}", str(req.value))
        
        # Invia la notifica via websocket (opzionale) o ricarica i settaggi
        await r.close()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Errore aggiornamento setting: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/force_gym")
async def api_force_gym():
    """Pubblica un comando su Redis per far partire la palestra su Titano."""
    try:
        r = aioredis.from_url(REDIS_URL)
        await r.publish("system_commands", json.dumps({"command": "force_gym"}))
        await r.close()
        return {"status": "success", "message": "Comando inviato a Titano!"}
    except Exception as e:
        logger.error(f"Errore invio system command: {e}")
        return {"status": "error", "message": str(e)}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"Nuovo client Dashboard connesso. Totale: {len(connected_clients)}")
    try:
        while True:
            # Mantieni la connessione aperta
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info("Client Dashboard disconnesso.")

async def redis_listener():
    logger.info("Avviato Redis Listener per la Dashboard...")
    try:
        r = aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        # Iscrizione a tutti i canali vitali della Fase 4 (Multi-Agent)
        await pubsub.subscribe("audit_requests", "audit_actions", "portfolio_status")
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                channel = message['channel'].decode('utf-8')
                try:
                    # Invia il messaggio a tutti i browser connessi
                    data = json.loads(message['data'])
                    payload = json.dumps({"channel": channel, "data": data})
                    
                    # Raccogliamo i client morti per rimuoverli
                    dead_clients = set()
                    for client in connected_clients:
                        try:
                            await client.send_text(payload)
                        except Exception:
                            dead_clients.add(client)
                            
                    for dead in dead_clients:
                        connected_clients.remove(dead)
                        
                except Exception as e:
                    logger.error(f"Errore parsing messaggio Redis: {e}")
                    
    except Exception as e:
        logger.error(f"Errore connessione Redis nella Dashboard: {e}")
        await asyncio.sleep(5)
        # Riavvia il listener in caso di crash
        asyncio.create_task(redis_listener())

@app.on_event("startup")
async def startup_event():
    # 1. Carica DB in Redis
    try:
        settings = await asyncio.to_thread(db.get_settings)
        if settings:
            r = aioredis.from_url(REDIS_URL)
            pipe = r.pipeline()
            for k, v in settings.items():
                pipe.set(f"config:{k}", str(v))
            await pipe.execute()
            await r.close()
            logger.info(f"Caricate {len(settings)} impostazioni da DB a Redis.")
    except Exception as e:
        logger.error(f"Errore caricamento impostazioni iniziali: {e}")
        
    # 2. Avvia listener
    task = asyncio.create_task(redis_listener())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    # 3. Avvia lo scraper storico in background come processo separato
    try:
        scraper_path = os.path.join(BASE_DIR, "historical_data_scraper.py")
        subprocess.Popen([sys.executable, scraper_path])
        logger.info("🤖 Avviato Demone Historical Data Scraper in background.")
    except Exception as e:
        logger.error(f"❌ Errore avvio scraper: {e}")
