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
                data = json.loads(message['data'])
                epic = data.get("epic")
                direction = data.get("direction")
                size_pct = data.get("size_pct", 5.0)
                
                logger.info(f"Ricevuto ordine da Titano: {direction} su {epic} (Size: {size_pct}%)")
                
                open_positions = api.get_all_positions()
                # Check if we already have a position open for this epic
                existing_pos = None
                for pos in open_positions:
                    if pos.get('market', {}).get('epic') == epic:
                        existing_pos = pos
                        break
                        
                if direction == "SELL":
                    if existing_pos:
                        logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione aperta.")
                        api.close_position_by_epic(epic)
                    else:
                        logger.info(f"Ignorato SELL su {epic} (nessuna posizione aperta da chiudere).")
                
                elif direction == "BUY":
                    if existing_pos:
                        logger.info(f"Posizione già aperta su {epic}. Ignoro il segnale di BUY ripetuto.")
                    else:
                        balance = api.get_account_balance()
                        cash_to_invest = balance * (size_pct / 100.0)
                        
                        price = api.get_market_price(epic)
                        if price > 0:
                            qty = cash_to_invest / price
                            min_size = api.get_min_deal_size(epic)
                            if qty < min_size:
                                qty = min_size # Forza dimensione minima per permettere al trade di passare
                            
                            logger.info(f"Esecuzione BUY su {epic} | Qty: {qty} (Investimento stimato: €{cash_to_invest:.2f})")
                            res = api.place_order(epic=epic, direction="BUY", size=qty)
                            if "dealReference" in res:
                                logger.info(f"✅ Ordine Eseguito con successo su {epic}!")
                            else:
                                logger.error(f"❌ Fallimento Esecuzione su {epic}: {res}")
            except Exception as e:
                logger.error(f"Errore durante l'elaborazione dell'ordine: {e}")

if __name__ == "__main__":
    asyncio.run(execution_manager_loop())
