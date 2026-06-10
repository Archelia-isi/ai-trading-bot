from fastapi import FastAPI
import asyncio
import logging
import os
import json
import math
import redis.asyncio as aioredis
from capital_api import CapitalComAPI

def safe_float(v):
    try:
        val = float(v)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return val
    except:
        return 0.0

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

INITIAL_CAPITAL = 89500.0 # Capitale Iniziale al lancio del software

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
                
                # PROTEZIONE ANTI-DISCONNESSIONE: 
                # Se la chiamata fallisce (ritorna None), NON pubblichiamo un array vuoto
                # altrimenti l'Esattore pensa che i trade siano stati chiusi.
                if raw_positions is None:
                    logger.warning("Disconnessione temporanea da Capital.com. Attendo il prossimo ciclo...")
                    await asyncio.sleep(2)
                    continue
                
                open_positions = []
                current_pnl_usd = 0.0
                
                for p in raw_positions:
                    pos = p.get('position', {})
                    market = p.get('market', {})
                    
                    epic = market.get('epic', 'UNKNOWN')
                    direction = pos.get('direction', 'BUY')
                    size_abs = pos.get('size', 0)
                    
                    # La leva su Capital.com si trova nell'oggetto 'position'
                    leverage = pos.get('leverage', 1)
                        
                    upl = pos.get('upl', 0.0)
                    
                    size_pct = 0.0
                    notional_usd = size_abs * market.get('offer', 1)
                    margin_usd = notional_usd / leverage
                    
                    if portfolio_state["total_capital"] > 0:
                        size_pct = (notional_usd / leverage / portfolio_state["total_capital"]) * 100
                        
                    open_positions.append({
                        "epic": epic,
                        "direction": direction,
                        "size": safe_float(size_pct),
                        "leverage": leverage,
                        "margin_usd": safe_float(margin_usd),
                        "notional_usd": safe_float(notional_usd),
                        "upl": safe_float(upl),
                        "pnl_pct": safe_float((upl / margin_usd * 100) if margin_usd > 0 else 0.0),
                        "asset_move_pct": safe_float((upl / notional_usd * 100) if notional_usd > 0 else 0.0)
                    })
                    current_pnl_usd += upl
                    
                invested_capital = margin_info.get("margin", 0.0)
                available_capital = margin_info.get("available", portfolio_state["total_capital"])
                
                portfolio_state["invested_capital"] = safe_float(invested_capital)
                portfolio_state["available_capital"] = safe_float(available_capital)
                portfolio_state["open_positions"] = open_positions
                portfolio_state["current_pnl_pct"] = safe_float((current_pnl_usd / portfolio_state["total_capital"] * 100) if portfolio_state["total_capital"] > 0 else 0.0)
                
                # Calcolo PnL Storico (Dall'inizio del software)
                total_historic_pnl_usd = portfolio_state["total_capital"] - INITIAL_CAPITAL
                portfolio_state["historic_pnl_usd"] = safe_float(total_historic_pnl_usd)
                portfolio_state["historic_pnl_pct"] = safe_float((total_historic_pnl_usd / INITIAL_CAPITAL) * 100)
                
                # Calcolo PnL Giornaliero Capitalizzato (Daily Compounding)
                try:
                    # Legge il capitale di inizio giornata da Redis. Se non c'è, usa INITIAL_CAPITAL (come richiesto per oggi)
                    redis_daily_cap = await r.get("daily_starting_capital")
                    if redis_daily_cap:
                        daily_base = float(redis_daily_cap)
                    else:
                        daily_base = INITIAL_CAPITAL
                except:
                    daily_base = INITIAL_CAPITAL
                    
                if daily_base <= 0: daily_base = 1.0 # Prevenzione div/0
                
                portfolio_state["daily_starting_capital"] = safe_float(daily_base)
                daily_pnl_usd = portfolio_state["total_capital"] - daily_base
                portfolio_state["daily_pnl_usd"] = safe_float(daily_pnl_usd)
                portfolio_state["daily_pnl_pct"] = safe_float((daily_pnl_usd / daily_base) * 100)
            
            # Leggi stato armato per esporlo (se serve) alla UI o log
            try:
                is_armed_str = await r.get("system_armed")
                if is_armed_str is not None:
                    portfolio_state["is_trading_locked"] = not (is_armed_str.decode('utf-8') == "true" if isinstance(is_armed_str, bytes) else is_armed_str == "true")
            except:
                pass

            # Pubblica su Redis per la Dashboard e salvalo in cache
            json_dump = json.dumps(portfolio_state)
            await r.publish("portfolio_status", json_dump)
            await r.set("latest_portfolio_status", json_dump)
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
                            existing_dir = existing_pos.get('position', {}).get('direction', 'BUY') if existing_pos else None
                            
                            if existing_dir == "BUY":
                                logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione Long aperta.")
                                api.close_position_by_epic(epic)
                                await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Long", "status": "APPROVED"}))
                            
                            action_str = "SELL (Accumulo)" if existing_dir == "SELL" else "SELL (Stop & Reverse)" if existing_dir == "BUY" else "SELL"
                            
                            balance = api.get_account_balance()
                            cash_to_invest = balance * (size_pct / 100.0)
                            
                            price = api.get_market_price(epic)
                            if price > 0:
                                qty = cash_to_invest / price
                                min_size = api.get_min_deal_size(epic)
                                if qty < min_size:
                                    qty = min_size
                                
                                # Check Sistema Armato prima di lanciare su Capital.com
                                is_armed_str = await r.get("system_armed")
                                is_armed = False
                                if is_armed_str is not None:
                                    is_armed = (is_armed_str.decode('utf-8') == "true" if isinstance(is_armed_str, bytes) else is_armed_str == "true")

                                if not is_armed:
                                    logger.info(f"🛡️ DRY RUN (Disarmato): Simulo {action_str} su {epic} | Qty: {qty}")
                                    res = {"dealReference": f"dry_run_{epic}_{direction}"}
                                else:
                                    logger.info(f"Esecuzione {action_str} su {epic} | Qty: {qty} (Investimento stimato: ${cash_to_invest:.2f})")
                                    res = api.place_order(epic=epic, direction="SELL", size=qty)
                                
                                if "dealReference" in res:
                                    logger.info(f"✅ Ordine {action_str} Eseguito con successo su {epic}!")
                                    await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "APPROVED"}))
                                    
                                    genesis_req = {
                                        "epic": epic,
                                        "direction": direction,
                                        "source": data.get("source", "TITANO_V6_SHORT"),
                                        "votes_mean": data.get("xgb_prob", data.get("prob", 0.5)),
                                        "size": size_pct,
                                        "price": price
                                    }
                                    await r.publish("supervisor_trade_genesis", json.dumps(genesis_req))
                                else:
                                    logger.error(f"❌ Ordine {action_str} Fallito su {epic}: {res}")
                                    await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "ERROR"}))
                        
                        elif direction == "BUY":
                            existing_dir = existing_pos.get('position', {}).get('direction', 'BUY') if existing_pos else None
                            
                            if existing_dir == "SELL":
                                logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione Short aperta.")
                                api.close_position_by_epic(epic)
                                await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Short", "status": "APPROVED"}))
                                
                            action_str = "BUY (Accumulo)" if existing_dir == "BUY" else "BUY (Stop & Reverse)" if existing_dir == "SELL" else "BUY"
                            
                            balance = api.get_account_balance()
                            cash_to_invest = balance * (size_pct / 100.0)
                            
                            price = api.get_market_price(epic)
                            if price > 0:
                                qty = cash_to_invest / price
                                min_size = api.get_min_deal_size(epic)
                                if qty < min_size:
                                    qty = min_size
                                
                                # Check Sistema Armato prima di lanciare su Capital.com
                                is_armed_str = await r.get("system_armed")
                                is_armed = False
                                if is_armed_str is not None:
                                    is_armed = (is_armed_str.decode('utf-8') == "true" if isinstance(is_armed_str, bytes) else is_armed_str == "true")

                                if not is_armed:
                                    logger.info(f"🛡️ DRY RUN (Disarmato): Simulo {action_str} su {epic} | Qty: {qty}")
                                    res = {"dealReference": f"dry_run_{epic}_{direction}"}
                                else:
                                    logger.info(f"Esecuzione {action_str} su {epic} | Qty: {qty} (Investimento stimato: ${cash_to_invest:.2f})")
                                    res = api.place_order(epic=epic, direction="BUY", size=qty)
                                
                                if "dealReference" in res:
                                    logger.info(f"✅ Ordine {action_str} Eseguito con successo su {epic}!")
                                    await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "APPROVED"}))
                                    
                                    # Genera la Genesi del Trade per il Supervisore
                                    genesis_req = {
                                        "epic": epic,
                                        "direction": direction,
                                        "source": data.get("source", "TITANO_V6"),
                                        "votes_mean": data.get("xgb_prob", data.get("prob", 0.5)),
                                        "size": size_pct,
                                        "price": price
                                    }
                                    await r.publish("supervisor_trade_genesis", json.dumps(genesis_req))
                                else:
                                    logger.error(f"❌ Ordine {action_str} Fallito su {epic}: {res}")
                                    await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "ERROR"}))
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
