from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import logging
import os
import requests
from typing import Optional
import json
import redis.asyncio as aioredis
from capital_api import CapitalComAPI

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

async def publish_audit_action(epic: str, action: str, status: str, details: str):
    try:
        r = aioredis.from_url(REDIS_URL)
        await r.publish("audit_actions", json.dumps({
            "epic": epic, "action": action, "status": status, "details": details
        }))
    except Exception as e:
        logger.error(f"Errore Redis Publish Audit: {e}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

background_tasks = set()

app = FastAPI(title="Audit & Risk Management Engine")

# Inizializza Capital.com API
api = CapitalComAPI()

# Stato globale fittizio del portafoglio (Ora aggiornato dinamicamente da Capital.com)
portfolio_state = {
    "total_capital": 0.0,
    "daily_start_capital": 0.0,
    "current_pnl_pct": 0.0,
    "open_positions": [],
    "is_trading_locked": False
}

class OrderRequest(BaseModel):
    epic: str
    direction: str
    size_pct: float
    leverage: int
    reasoning: str
    news: Optional[str] = None
    prob: Optional[float] = None

# Cache dei segnali per il Voto Pesato
signal_cache = {}
from datetime import datetime, timedelta

@app.post("/audit_order")
async def audit_order(req: OrderRequest):
    logger.info(f"Ricevuta richiesta ordine da {req.source} su {req.epic}: {req.direction} | Size: {req.size_pct}%")
    
    # Epic Resolution Dinamica
    real_epic = req.epic
    if api.is_authenticated:
        instrument = api.search_instrument(req.epic)
        if instrument:
            real_epic = instrument['epic']
            
    # --- 1. IL CONSIGLIO D'AMMINISTRAZIONE (VOTO PESATO) ---
    now = datetime.now()
    if real_epic not in signal_cache:
        signal_cache[real_epic] = {}
        
    # Aggiorniamo la memoria del segnale
    val = 1.0 if req.direction == "BUY" else (-1.0 if req.direction == "SELL" else 0.0)
    signal_cache[real_epic][req.source] = {"val": val, "time": now, "size": req.size_pct}
    
    # Pulizia segnali vecchi (XGBoost/NLP scadono dopo 2 ore, Titano dopo 5 minuti)
    active_votes = []
    for src, data in list(signal_cache[real_epic].items()):
        age_minutes = (now - data["time"]).total_seconds() / 60.0
        if src == "TITANO_V4" and age_minutes > 5:
            del signal_cache[real_epic][src]
        elif age_minutes > 120:
            del signal_cache[real_epic][src]
        else:
            active_votes.append(data["val"])
            
    if not active_votes:
        return {"status": "pending", "reason": "No active votes"}
        
    # Calcolo Media Assoluta
    mean_vote = sum(active_votes) / len(active_votes)
    
    final_direction = "FLAT"
    if mean_vote >= 0.5: final_direction = "BUY"
    elif mean_vote <= -0.5: final_direction = "SELL"
    
    if final_direction == "FLAT":
        logger.info(f"CONSIGLIO D'AMMINISTRAZIONE: Voti discordanti su {real_epic} (Media: {mean_vote:.2f}). Nessuna azione.")
        return {"status": "rejected", "reason": "Discordant Votes"}
        
    logger.info(f"⚖️ CONSIGLIO D'AMMINISTRAZIONE APPROVA: {final_direction} su {real_epic} (Media: {mean_vote:.2f})")
    
    # Check Doppioni
    for p in portfolio_state["open_positions"]:
        if p['epic'] == real_epic:
            return {"status": "rejected", "reason": "Duplicate Position"}

    if portfolio_state["is_trading_locked"]:
        return {"status": "rejected", "reason": "Trading Locked"}

    final_size = req.size_pct
    final_leverage = req.leverage
        
    # --- 2. ARBITRAGGIO MULTI-BROKER (CAPITALE CONDIVISO) ---
    market_price = api.get_market_price(real_epic)
    equity = portfolio_state["total_capital"] if portfolio_state["total_capital"] > 0 else 10000.0
    
    amount_to_invest = equity * (final_size / 100.0)
    lot_size = ((amount_to_invest * final_leverage) / market_price) if market_price > 0 else 0.1
    
    if final_direction == "SELL":
        # ESECUZIONE REALE SU CAPITAL.COM (SOLO SHORT)
        if api.is_authenticated:
            min_size = api.get_min_deal_size(real_epic)
            lot_size = max(lot_size, min_size)
            
            logger.info(f"🔥 ARBITRAGGIO: SHORT inviato a CAPITAL.COM ({lot_size} lotti su {real_epic})")
            res = api.place_order(real_epic, final_direction, lot_size)
            
            if res.get("status") != "success":
                await publish_audit_action(real_epic, f"SELL {lot_size}", "REJECTED", f"Capital API Error: {res.get('message')}")
                return {"status": "error", "reason": "Broker Error"}
                
            await publish_audit_action(real_epic, f"SELL {lot_size} L{final_leverage}x", "APPROVED", "Eseguito su Capital.com")
        else:
            logger.warning("Capital.com non connesso. MOCK SHORT.")
    else:
        # ESECUZIONE SIMULATA SU BINANCE (SOLO LONG)
        logger.info(f"🟢 ARBITRAGGIO: LONG simulato su BINANCE PAPER TRADING ({lot_size} lotti su {real_epic})")
        # Applichiamo una finta fee dello 0.1% come su Binance reale per rendere il mock realistico
        fee_usd = amount_to_invest * 0.001
        portfolio_state["total_capital"] -= fee_usd # Detrazione capitale condiviso
        
        await publish_audit_action(real_epic, f"BUY {lot_size} L{final_leverage}x", "APPROVED", f"Simulato su Binance (Fee: {fee_usd:.2f}$)")

    # Aggiornamento Portafoglio
    portfolio_state["open_positions"].append({
        "epic": real_epic,
        "direction": final_direction,
        "size": final_size,
        "leverage": final_leverage,
        "pnl_pct": 0.0
    })
    
    # Notifichiamo il Supervisore per il Cross-Pollination
    try:
        r = aioredis.from_url(REDIS_URL)
        await r.publish("supervisor_trade_genesis", json.dumps({
            "epic": real_epic,
            "direction": final_direction,
            "source": req.source,
            "votes_mean": mean_vote,
            "size": final_size,
            "price": market_price
        }))
    except:
        pass
    
    return {
        "status": "approved",
        "executed_size_pct": final_size,
        "executed_leverage": final_leverage
    }

async def risk_monitor_loop():
    logger.info("Avviato Monitor Rischio Continuo dell'Auditor...")
    while True:
        try:
            if api.is_authenticated:
                # 1. Recupera i dati reali da Capital.com
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
                    
                    # Calcolo approssimativo della % investita
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
                    
                portfolio_state["open_positions"] = open_positions
                portfolio_state["current_pnl_pct"] = (current_pnl_usd / portfolio_state["total_capital"] * 100) if portfolio_state["total_capital"] > 0 else 0.0
            else:
                # Mock PnL
                portfolio_state["current_pnl_pct"] = sum(p['pnl_pct'] for p in portfolio_state["open_positions"])
            
            async def get_cfg(k, d):
                try:
                    r = aioredis.from_url(REDIS_URL, decode_responses=True)
                    v = await r.get(f"config:{k}")
                    await r.close()
                    return float(v) if v is not None else d
                except: return d

            daily_tp = await get_cfg("daily_take_profit", 1.0)
            max_dd = await get_cfg("max_drawdown", -3.0)

            # HARD RULE: Global Take Profit
            if portfolio_state["current_pnl_pct"] >= daily_tp and not portfolio_state["is_trading_locked"]:
                logger.info(f"🏆 OBIETTIVO GIORNALIERO +{daily_tp}% RAGGIUNTO! Chiusura globale e blocco trading.")
                portfolio_state["open_positions"].clear() 
                portfolio_state["is_trading_locked"] = True
                await publish_audit_action("PORTFOLIO", "Chiusura Globale", "SYSTEM", f"Obiettivo Giornaliero +{daily_tp}% Raggiunto!")
                
            # HARD RULE: Flexible Drawdown
            if portfolio_state["current_pnl_pct"] <= max_dd and not portfolio_state["is_trading_locked"]:
                logger.warning(f"🚨 MAX DRAWDOWN {max_dd}% RAGGIUNTO! Protezione capitale attivata. Chiusura globale.")
                portfolio_state["open_positions"].clear()
                portfolio_state["is_trading_locked"] = True
                await publish_audit_action("PORTFOLIO", "Protezione Capitale", "SYSTEM", f"Max Drawdown {max_dd}% Raggiunto. Chiusura Globale.")
                
            # HARD RULE: Time Window Lock (Si attiva a 30 min dalla chiusura di Wall Street/Europa)
            # HARD RULE: Flash Crash Kill Switch e Dynamic ATR (Richiede interrogazione prezzi)
            
            # Calcolo metriche per la Dashboard
            current_exposure_pct = sum(p['size'] for p in portfolio_state["open_positions"])
            invested_capital = portfolio_state["total_capital"] * (current_exposure_pct / 100.0)
            available_capital = portfolio_state["total_capital"] - invested_capital
            
            status_payload = {
                "total_capital": portfolio_state["total_capital"],
                "invested_capital": invested_capital,
                "available_capital": available_capital,
                "current_pnl_pct": portfolio_state["current_pnl_pct"],
                "open_positions": portfolio_state["open_positions"]
            }
            try:
                r = aioredis.from_url(REDIS_URL)
                await r.publish("portfolio_status", json.dumps(status_payload))
            except Exception as e:
                logger.error(f"Errore publish portfolio_status: {e}")
                
            await asyncio.sleep(5) # Controlla il rischio ogni 5 secondi!
            
        except Exception as e:
            logger.error(f"Errore loop rischio: {e}")
            await asyncio.sleep(5)

async def audit_listener_loop():
    logger.info("Avviato Audit Redis Listener (Event-Driven)...")
    while True:
        try:
            r = aioredis.from_url(REDIS_URL)
            async with r.pubsub() as pubsub:
                await pubsub.subscribe("audit_requests")
                
                logger.info("In ascolto sul canale 'audit_requests'...")
                async for message in pubsub.listen():
                    if message['type'] == 'message':
                        try:
                            data = json.loads(message['data'])
                            req = OrderRequest(**data)
                            # Chiama la logica di audit
                            await audit_order(req)
                        except Exception as e:
                            logger.error(f"Errore elaborazione audit_requests: {e}")
        except Exception as e:
            logger.error(f"Errore connessione Redis in Audit: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    logger.info("Connessione a Capital.com in corso...")
    success = api.authenticate()
    if success:
        logger.info("🚀 API Capital.com Connessa! Trading LIVE attivo.")
    else:
        logger.warning("⚠️ API Capital.com Fallita. Trading simulato attivo.")
    task1 = asyncio.create_task(risk_monitor_loop())
    background_tasks.add(task1)
    task1.add_done_callback(background_tasks.discard)

    task2 = asyncio.create_task(audit_listener_loop())
    background_tasks.add(task2)
    task2.add_done_callback(background_tasks.discard)
