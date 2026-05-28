import os
import json
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import redis.asyncio as aioredis

class LambdaRequest(BaseModel):
    lambda_value: float

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mission Control Dashboard")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Lista di tutti i client WebSocket connessi
connected_clients = set()

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/set_xgboost_lambda")
async def set_xgboost_lambda(req: LambdaRequest):
    logger.info(f"Ricevuta richiesta modifica XGBoost Lambda a {req.lambda_value}")
    r = await aioredis.from_url(REDIS_URL)
    await r.set("config:xgboost_lambda", str(req.lambda_value))
    await r.close()
    return {"status": "success", "lambda_value": req.lambda_value}

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
        r = await aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        # Iscrizione a tutti i canali vitali
        await pubsub.subscribe("news_alerts", "portfolio_alerts", "gemini_decisions", "audit_actions", "portfolio_status")
        
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
    asyncio.create_task(redis_listener())
