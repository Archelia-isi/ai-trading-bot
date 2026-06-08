import asyncio
import logging
import os
import json
import redis.asyncio as aioredis
from services.titano_engine.core.capital_api import CapitalComAPI

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
api = CapitalComAPI()

async def execution_manager_loop():
    logger.info("Avviato Esecutore 'Carta Bianca' (Fase 3). In attesa di ordini da Titano V6...")
    r = await aioredis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("execution_requests")
    
    api.authenticate()
    
    async for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                # Check bot status first
                bot_status_raw = await r.get("config:bot_active")
                bot_active = True
                if bot_status_raw and bot_status_raw.decode('utf-8') == 'false':
                    bot_active = False

                data = json.loads(message['data'])
                epic = data.get("epic")
                direction = data.get("direction")
                size_pct = data.get("size_pct", 5.0)
                
                logger.info(f"Ricevuto ordine da Titano: {direction} su {epic} (Size: {size_pct}%)")
                
                if not bot_active:
                    logger.warning(f"⏸ BOT FERMATO DALL'UTENTE. Ignoro l'ordine {direction} su {epic}.")
                    continue
                
                open_positions = api.get_all_positions()
                existing_pos = None
                existing_direction = None
                
                for pos in open_positions:
                    market_info = pos.get('market', {})
                    if market_info.get('epic') == epic:
                        existing_pos = pos
                        existing_direction = pos.get('position', {}).get('direction', '') # "BUY" o "SELL"
                        break
                        
                # FUNZIONE DI APPOGGIO PER PIAZZARE ORDINI
                def esegui_ordine(dir_str):
                    balance = api.get_account_balance()
                    cash_to_invest = balance * (size_pct / 100.0)
                    price = api.get_market_price(epic)
                    if price > 0:
                        qty = cash_to_invest / price
                        min_size = api.get_min_deal_size(epic)
                        if qty < min_size:
                            qty = min_size 
                        
                        logger.info(f"Esecuzione {dir_str} su {epic} | Qty: {qty} (Investimento stimato: €{cash_to_invest:.2f})")
                        res = api.place_order(epic=epic, direction=dir_str, size=qty)
                        if "dealReference" in res:
                            logger.info(f"✅ Ordine {dir_str} Eseguito con successo su {epic}!")
                        else:
                            logger.error(f"❌ Fallimento Esecuzione {dir_str} su {epic}: {res}")

                if direction == "SELL":
                    if existing_pos:
                        if existing_direction == "BUY":
                            logger.info(f"Inversione: Chiudo LONG su {epic} e apro SHORT.")
                            api.close_position_by_epic(epic)
                            esegui_ordine("SELL")
                        else:
                            logger.info(f"Posizione SHORT già aperta su {epic}. Ignoro segnale SELL ripetuto.")
                    else:
                        logger.info(f"Apro nuova posizione SHORT su {epic}.")
                        esegui_ordine("SELL")
                
                elif direction == "BUY":
                    if existing_pos:
                        if existing_direction == "SELL":
                            logger.info(f"Inversione: Chiudo SHORT su {epic} e apro LONG.")
                            api.close_position_by_epic(epic)
                            esegui_ordine("BUY")
                        else:
                            logger.info(f"Posizione LONG già aperta su {epic}. Ignoro segnale BUY ripetuto.")
                    else:
                        logger.info(f"Apro nuova posizione LONG su {epic}.")
                        esegui_ordine("BUY")
                        
                elif direction == "FLAT":
                    if existing_pos:
                        logger.info(f"Titano richiede FLAT. Chiudo la posizione {existing_direction} su {epic}.")
                        api.close_position_by_epic(epic)
                    else:
                        logger.debug(f"Segnale FLAT ignorato (nessuna posizione aperta su {epic}).")
            except Exception as e:
                logger.error(f"Errore durante l'elaborazione dell'ordine: {e}")

if __name__ == "__main__":
    asyncio.run(execution_manager_loop())
