from fastapi import FastAPI
import asyncio
import logging
import os
import json
import redis.asyncio as aioredis
from capital_api import CapitalComAPI

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
api = CapitalComAPI()

app = FastAPI(title="Execution Engine (Carta Bianca)")
background_tasks = set()

portfolio_state = {
    "total_capital": 0.0,
    "current_pnl_pct": 0.0,
    "open_positions": [],
    "is_trading_locked": False
}

async def portfolio_monitor_loop():
    logger.info("Avviato Monitor Portfolio dell'Esecutore (per la Dashboard)...")
    r = await aioredis.from_url(REDIS_URL)
    while True:
        try:
            if api.is_authenticated:
                margin_info = api.get_margin_info()
                new_equity = margin_info.get("equity", 0.0)
                if new_equity > 0:
                    portfolio_state["total_capital"] = new_equity
                
                raw_positions = api.get_all_positions()
                open_positions = []
                current_pnl_usd = 0.0
                
                for p in raw_positions:
                    pos = p.get('position', {})
                    market = p.get('market', {})
                    
                    epic = market.get('epic', 'UNKNOWN')
                    direction = pos.get('direction', 'BUY')
                    size_abs = pos.get('size', 0)
                    
                    margin_factor = market.get('marginFactor')
                    if margin_factor and float(margin_factor) > 0:
                        leverage = int(round(1 / float(margin_factor)))
                    else:
                        leverage = market.get('leverage', 1)
                        
                    upl = pos.get('upl', 0.0)
                    
                    size_pct = 0.0
                    if portfolio_state["total_capital"] > 0:
                        size_pct = ((size_abs * market.get('offer', 1)) / leverage / portfolio_state["total_capital"]) * 100
                        
                    open_positions.append({
                        "epic": epic,
                        "direction": direction,
                        "size": size_pct,
                        "leverage": leverage,
                        "pnl_pct": (upl / portfolio_state["total_capital"] * 100) if portfolio_state["total_capital"] > 0 else 0.0
                    })
                    current_pnl_usd += upl
                    
                invested_capital = margin_info.get("margin", 0.0)
                available_capital = margin_info.get("available", portfolio_state["total_capital"])
                
                portfolio_state["invested_capital"] = invested_capital
                portfolio_state["available_capital"] = available_capital
                portfolio_state["open_positions"] = open_positions
                portfolio_state["current_pnl_pct"] = (current_pnl_usd / portfolio_state["total_capital"] * 100) if portfolio_state["total_capital"] > 0 else 0.0
            
            # Pubblica su Redis per la Dashboard
            await r.publish("portfolio_status", json.dumps(portfolio_state))
        except Exception as e:
            logger.error(f"Errore nel portfolio_monitor_loop: {e}")
        
        await asyncio.sleep(5)


async def execution_manager_loop():
    logger.info("Avviato Esecutore 'Carta Bianca' (Fase 3). In attesa di ordini da Titano V6...")
    r = await aioredis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("execution_requests")
    
    while True:
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        epic = data.get("epic")
                        direction = data.get("direction")
                        size_pct = data.get("size_pct", 5.0)
                        
                        logger.info(f"Ricevuto ordine da Titano: {direction} su {epic} (Size: {size_pct}%)")
                        
                        open_positions = api.get_all_positions()
                        existing_pos = None
                        for pos in open_positions:
                            if pos.get('market', {}).get('epic') == epic:
                                existing_pos = pos
                                break
                                
                        if direction == "SELL":
                            if existing_pos:
                                logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione aperta.")
                                api.close_position_by_epic(epic)
                                await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Long da Titano", "status": "APPROVED"}))
                            else:
                                logger.info(f"Ignorato SELL su {epic} (nessuna posizione aperta da chiudere).")
                                await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Skip SELL (Nessuna Posizione)", "status": "REJECTED"}))
                        
                        elif direction == "BUY":
                            if existing_pos:
                                logger.info(f"Posizione già aperta su {epic}. Ignoro il segnale di BUY ripetuto.")
                                await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Skip BUY (Posizione Esistente)", "status": "REJECTED"}))
                            else:
                                balance = api.get_account_balance()
                                cash_to_invest = balance * (size_pct / 100.0)
                                
                                price = api.get_market_price(epic)
                                if price > 0:
                                    qty = cash_to_invest / price
                                    min_size = api.get_min_deal_size(epic)
                                    if qty < min_size:
                                        qty = min_size
                                    
                                    logger.info(f"Esecuzione BUY su {epic} | Qty: {qty} (Investimento stimato: €{cash_to_invest:.2f})")
                                    res = api.place_order(epic=epic, direction="BUY", size=qty)
                                    if "dealReference" in res:
                                        logger.info(f"✅ Ordine Eseguito con successo su {epic}!")
                                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": f"BUY {qty}", "status": "APPROVED"}))
                                    else:
                                        logger.error(f"❌ Fallimento Esecuzione su {epic}: {res}")
                                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": f"Fallimento BUY", "status": "REJECTED"}))
                    except Exception as e:
                        logger.error(f"Errore durante l'elaborazione dell'ordine: {e}")
        except Exception as e:
            logger.error(f"Errore connessione Redis Execution: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    logger.info("Connessione a Capital.com in corso per Esecutore...")
    success = api.authenticate()
    if success:
        logger.info("🚀 API Capital.com Connessa per Esecutore Carta Bianca.")
    task1 = asyncio.create_task(execution_manager_loop())
    background_tasks.add(task1)
    task1.add_done_callback(background_tasks.discard)
    
    task2 = asyncio.create_task(portfolio_monitor_loop())
    background_tasks.add(task2)
    task2.add_done_callback(background_tasks.discard)

@app.get("/")
def read_root():
    return {"status": "Execution Engine Carta Bianca Online"}
