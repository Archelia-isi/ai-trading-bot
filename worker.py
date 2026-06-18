import asyncio
import logging
import sys
import subprocess
import os
import json
import redis.asyncio as aioredis
from services.titano_engine.core.capital_api import CapitalComAPI

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
api = CapitalComAPI()

# Dizionario globale di lock per prevenire spam asincrono sullo stesso asset
processing_assets = {}

async def process_order_message(data, r, api):
    epic = data.get("epic")
    direction = data.get("direction")
    size_pct = data.get("size_pct", 5.0)
    
    # 1. CONTROLLO LOCK SERIALE
    if processing_assets.get(epic, False):
        logger.warning(f"⏳ Asset {epic} è già in transazione. Segnale {direction} ignorato per prevenire spam (cooldown).")
        return
        
    # Blocca l'asset
    processing_assets[epic] = True
    
    try:
        # Check bot status first
        bot_status_raw = await r.get("config:bot_active")
        bot_active = True
        if bot_status_raw and bot_status_raw.decode('utf-8') == 'false':
            bot_active = False

        logger.info(f"Ricevuto ordine da Titano: {direction} su {epic} (Size: {size_pct}%)")
        
        if not bot_active:
            logger.warning(f"⏸ BOT FERMATO DALL'UTENTE. Ignoro l'ordine {direction} su {epic}.")
            return
        
        # 2. CHIAMATE API OFF-THREAD (non bloccano l'event loop)
        open_positions = await asyncio.to_thread(api.get_all_positions)
        existing_pos = None
        existing_direction = None
        
        for pos in open_positions:
            market_info = pos.get('market', {})
            if market_info.get('epic') == epic:
                existing_pos = pos
                existing_direction = pos.get('position', {}).get('direction', '') # "BUY" o "SELL"
                break
                
        # FUNZIONE DI APPOGGIO ASINCRONA PER PIAZZARE ORDINI
        async def esegui_ordine_async(dir_str):
            balance = await asyncio.to_thread(api.get_account_balance)
            cash_to_invest = balance * (size_pct / 100.0)
            price = await asyncio.to_thread(api.get_market_price, epic)
            
            if price > 0:
                qty = cash_to_invest / price
                min_size = await asyncio.to_thread(api.get_min_deal_size, epic)
                if qty < min_size:
                    qty = min_size 
                
                logger.info(f"Esecuzione {dir_str} su {epic} | Qty: {qty} (Investimento stimato: €{cash_to_invest:.2f})")
                res = await asyncio.to_thread(api.place_order, epic=epic, direction=dir_str, size=qty)
                if "dealReference" in res:
                    logger.info(f"✅ Ordine {dir_str} Eseguito con successo su {epic}!")
                else:
                    logger.error(f"❌ Fallimento Esecuzione {dir_str} su {epic}: {res}")

        # LOGICA DI TRADING
        if direction == "SELL":
            if existing_pos:
                if existing_direction == "BUY":
                    logger.info(f"Inversione: Chiudo LONG su {epic} e apro SHORT.")
                    await asyncio.to_thread(api.close_position_by_epic, epic)
                    await esegui_ordine_async("SELL")
                else:
                    logger.info(f"Posizione SHORT già aperta su {epic}. Ignoro segnale SELL ripetuto.")
            else:
                logger.info(f"Apro nuova posizione SHORT su {epic}.")
                await esegui_ordine_async("SELL")
        
        elif direction == "BUY":
            if existing_pos:
                if existing_direction == "SELL":
                    logger.info(f"Inversione: Chiudo SHORT su {epic} e apro LONG.")
                    await asyncio.to_thread(api.close_position_by_epic, epic)
                    await esegui_ordine_async("BUY")
                else:
                    logger.info(f"Posizione LONG già aperta su {epic}. Ignoro segnale BUY ripetuto.")
            else:
                logger.info(f"Apro nuova posizione LONG su {epic}.")
                await esegui_ordine_async("BUY")
                
        elif direction == "FLAT":
            if existing_pos:
                logger.info(f"Titano richiede FLAT. Chiudo la posizione {existing_direction} su {epic}.")
                await asyncio.to_thread(api.close_position_by_epic, epic)
            else:
                logger.debug(f"Segnale FLAT ignorato (nessuna posizione aperta su {epic}).")
                
        # 3. IL RESPIRO (COOLDOWN DI SICUREZZA)
        # Permette ai server di Capital.com di allineare l'eventual consistency
        await asyncio.sleep(2)

    except Exception as e:
        logger.error(f"Errore durante l'elaborazione dell'ordine su {epic}: {e}")
    finally:
        # Sblocca l'asset per i futuri segnali
        processing_assets[epic] = False

async def execution_manager_loop():
    logger.info("Avviato Esecutore 'Carta Bianca' (Fase 3). In attesa di ordini da Titano V6...")
    r = await aioredis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("execution_requests")
    
    # L'autenticazione iniziale è meglio farla sincrona ma off-thread per non bloccare startup
    await asyncio.to_thread(api.authenticate)
    
    async for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                data = json.loads(message['data'])
                # Sgancia il task in concorrenza pura (Fire and Forget)
                asyncio.create_task(process_order_message(data, r, api))
            except Exception as e:
                logger.error(f"Errore nel parsing del messaggio di root: {e}")

from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Worker Online"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(execution_manager_loop())
    try:
        scraper_path = os.path.join(os.path.dirname(__file__), "services", "dashboard_engine", "historical_data_scraper.py")
        subprocess.Popen([sys.executable, scraper_path])
        logger.info("🤖 Avviato Demone Historical Data Scraper in background dal worker.")
    except Exception as e:
        logger.error(f"❌ Errore avvio scraper dal worker: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
