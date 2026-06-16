from fastapi import FastAPI
import asyncio
import logging
import os
import json
import math
import time
import redis.asyncio as aioredis
import sys
import os
# Assicuriamoci che python trovi i moduli locali (capital_api, risk_manager)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from capital_api import CapitalComAPI
from risk_manager import DynamicAssetResolver

# HARD CODE OVERRIDE: Mantiene il sistema in test per 48 ore
DRY_RUN = True

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
asset_resolver = DynamicAssetResolver()

app = FastAPI(title="Execution Engine (Carta Bianca)")
background_tasks = set()

portfolio_state = {
    "total_capital": 0.0,
    "current_pnl_pct": 0.0,
    "open_positions": [],
    "is_trading_locked": False
}

INITIAL_CAPITAL = None # Capitale Iniziale dinamico dal broker

async def portfolio_monitor_loop():
    logger.info("Avviato Monitor Portfolio dell'Esecutore (per la Dashboard)...")
    r = await aioredis.from_url(REDIS_URL)
    global INITIAL_CAPITAL
    while True:
        try:
            if api.is_authenticated:
                margin_info = api.get_margin_info()
                new_equity = margin_info.get("equity", 0.0)
                if new_equity > 0:
                    portfolio_state["total_capital"] = new_equity
                    
                    stored_ic = await r.get("bot_initial_capital")
                    if stored_ic:
                        INITIAL_CAPITAL = float(stored_ic)
                    else:
                        INITIAL_CAPITAL = new_equity
                        await r.set("bot_initial_capital", str(INITIAL_CAPITAL))
                    
                    portfolio_state["initial_capital"] = safe_float(INITIAL_CAPITAL)
                
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


asset_locks = {}
last_execution_time = {}

async def process_order_message(data, r, api):
    ticker_feed = data.get("epic")
    direction = data.get("direction")
    xgb_prob = float(data.get("xgb_prob", 0.5))
    
    # Risoluzione Dinamica dell'Asset (Capital.com Epic)
    epic = await asset_resolver.resolve_epic(ticker_feed)
    if not epic:
        logger.error(f"Impossibile risolvere Epic per {ticker_feed}. Ordine ignorato.")
        return
    
    # Criterio di Kelly Dinamico (W - ((1 - W) / R)), assumendo R=1
    kelly_fraction = xgb_prob - ((1.0 - xgb_prob) / 1.0)
    if kelly_fraction < 0: kelly_fraction = 0.01 # Minimo 1% se sfavorevole ma passa
    
    # Capping tra 1% e 15% del capitale
    size_pct = min(max(kelly_fraction * 100.0, 1.0), 15.0) if direction != "FLAT" else 0.0
    
    lock = asset_locks.setdefault(epic, asyncio.Lock())
    if lock.locked():
        logger.warning(f"⏳ Asset {epic} è già in transazione (Lock Attivo). Segnale {direction} ignorato.")
        return
        
    async with lock:
        try:
            now = time.time()
            if epic in last_execution_time and (now - last_execution_time[epic]) < 10.0:
                logger.warning(f"⏳ Cooldown di 10s attivo su {epic}. Segnale scartato.")
                return
                
            logger.info(f"Ricevuto ordine da Titano: {direction} su {epic} (Size: {size_pct}%)")
            
            # Leggiamo le posizioni dalla cache locale invece di intasare le API
            open_positions = portfolio_state.get("open_positions", [])
            existing_pos = None
            for pos in open_positions:
                if pos.get('epic') == epic:
                    # Ricreiamo la struttura minima necessaria per mantenere la compatibilità
                    existing_pos = {'position': {'direction': pos.get('direction', 'BUY')}}
                    break
                
            # Se è FLAT ma non abbiamo posizioni, possiamo ignorare in sicurezza senza chiamare API
            if direction == "FLAT" and not existing_pos:
                pass # Ignorato a costo zero
            else:
                # --- GESTIONE SINCRONA ORARI DI MERCATO (FROZEN STATE) ---
                # Evitiamo chiamate POST a vuoto e crash da timeout se il mercato è chiuso o sta chiudendo
                is_closing = await asyncio.to_thread(api.is_market_closing_soon, epic, 15)
                if is_closing:
                    logger.warning(f"🧊 Mercato Frozen per {epic} (Chiuso/Pausa). Segnale {direction} scartato per prevenire REJECTED.")
                    return
                    
                # FORZATURA SICUREZZA NUOVI CERVELLI (48h)
                is_armed = False if DRY_RUN else is_armed
                if DRY_RUN:
                    logger.info("🔒 [SYSTEM] DRY_RUN_FORZATO attivo (Hardcode override): Nessun capitale reale a rischio.")

            if direction == "FLAT":
                if existing_pos:
                    if not is_armed:
                        logger.info(f"🛡️ DRY RUN (Disarmato): Simulo Chiusura FLAT su {epic}")
                    else:
                        logger.info(f"Titano ha azzerato l'esposizione. Chiusura posizione su {epic}.")
                        await asyncio.to_thread(api.close_position_by_epic, epic)
                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Totale", "status": "APPROVED"}))
                
            elif direction == "SELL":
                existing_dir = existing_pos.get('position', {}).get('direction', 'BUY') if existing_pos else None
                
                if existing_dir == "BUY":
                    if not is_armed:
                        logger.info(f"🛡️ DRY RUN (Disarmato): Simulo Chiusura Long aperta su {epic}")
                    else:
                        logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione Long aperta.")
                        await asyncio.to_thread(api.close_position_by_epic, epic)
                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Long", "status": "APPROVED"}))
                
                action_str = "SELL (Accumulo)" if existing_dir == "SELL" else "SELL (Stop & Reverse)" if existing_dir == "BUY" else "SELL"
                
                # Leggiamo il capitale dalla cache locale invece di interpellare Capital.com
                balance = portfolio_state.get("total_capital", 0.0)
                cash_to_invest = balance * (size_pct / 100.0)
                
                price = await asyncio.to_thread(api.get_market_price, epic)
                if price > 0:
                    qty = cash_to_invest / price
                    min_size = await asyncio.to_thread(api.get_min_deal_size, epic)
                    if qty < min_size:
                        qty = min_size
                    
                    if not is_armed:
                        logger.info(f"🛡️ DRY RUN (Disarmato): Simulo {action_str} su {epic} | Qty: {qty}")
                        res = {"dealReference": f"dry_run_{epic}_{direction}"}
                    else:
                        logger.info(f"Esecuzione {action_str} su {epic} | Qty: {qty} (Investimento stimato: ${cash_to_invest:.2f})")
                        res = await asyncio.to_thread(api.place_order, epic=epic, direction="SELL", size=qty)
                    
                    if "dealReference" in res:
                        logger.info(f"✅ Ordine {action_str} Eseguito con successo su {epic}!")
                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "APPROVED"}))
                        
                        genesis_req = {
                            "epic": epic,
                            "direction": direction,
                            "source": data.get("source", "TITANO_V6_SHORT"),
                            "votes_mean": data.get("prob", 0.5),
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
                    if not is_armed:
                        logger.info(f"🛡️ DRY RUN (Disarmato): Simulo Chiusura Short aperta su {epic}")
                    else:
                        logger.info(f"Titano ha invertito la view su {epic}. Chiusura posizione Short aperta.")
                        await asyncio.to_thread(api.close_position_by_epic, epic)
                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": "Chiusura Short", "status": "APPROVED"}))
                    
                action_str = "BUY (Accumulo)" if existing_dir == "BUY" else "BUY (Stop & Reverse)" if existing_dir == "SELL" else "BUY"
                
                # Leggiamo il capitale dalla cache locale invece di interpellare Capital.com
                balance = portfolio_state.get("total_capital", 0.0)
                cash_to_invest = balance * (size_pct / 100.0)
                
                price = await asyncio.to_thread(api.get_market_price, epic)
                if price > 0:
                    qty = cash_to_invest / price
                    min_size = await asyncio.to_thread(api.get_min_deal_size, epic)
                    if qty < min_size:
                        qty = min_size
                    
                    if not is_armed:
                        logger.info(f"🛡️ DRY RUN (Disarmato): Simulo {action_str} su {epic} | Qty: {qty}")
                        res = {"dealReference": f"dry_run_{epic}_{direction}"}
                    else:
                        logger.info(f"Esecuzione {action_str} su {epic} | Qty: {qty} (Investimento stimato: ${cash_to_invest:.2f})")
                        res = await asyncio.to_thread(api.place_order, epic=epic, direction="BUY", size=qty)
                    
                    if "dealReference" in res:
                        logger.info(f"✅ Ordine {action_str} Eseguito con successo su {epic}!")
                        await r.publish("audit_actions", json.dumps({"epic": epic, "action": action_str, "status": "APPROVED"}))
                        
                        genesis_req = {
                            "epic": epic,
                            "direction": direction,
                            "source": data.get("source", "TITANO_V6"),
                            "votes_mean": data.get("prob", 0.5),
                            "size": size_pct,
                            "price": price
                        }
                        await r.publish("supervisor_trade_genesis", json.dumps(genesis_req))
                    else:
                        logger.error(f"❌ Ordine {action_str} Fallito su {epic}: {res}")
        except Exception as e:
            logger.error(f"Errore durante l'elaborazione dell'ordine su {epic}: {e}")
        finally:
            last_execution_time[epic] = time.time()

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
                        asyncio.create_task(process_order_message(data, r, api))
                    except Exception as e:
                        logger.error(f"Errore parsing messaggio: {e}")
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

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
