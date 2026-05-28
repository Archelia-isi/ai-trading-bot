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
        r = await aioredis.from_url(REDIS_URL)
        await r.publish("audit_actions", json.dumps({
            "epic": epic, "action": action, "status": status, "details": details
        }))
    except Exception as e:
        logger.error(f"Errore Redis Publish Audit: {e}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

@app.post("/audit_order")
async def audit_order(req: OrderRequest):
    logger.info(f"Ricevuta richiesta ordine da Gemini su {req.epic}: {req.direction} | Size: {req.size_pct}% | Leva: {req.leverage}x")
    
    # Epic Resolution Dinamica & Duplicate Check
    if api.is_authenticated:
        instrument = api.search_instrument(req.epic)
        if not instrument:
            logger.error(f"AUDIT REJECT: Strumento non trovato su Capital.com per {req.epic}")
            await publish_audit_action(req.epic, f"{req.direction}", "REJECTED", "Strumento non trovato sul broker")
            return {"status": "rejected", "reason": "Epic not found"}
            
        real_epic = instrument['epic']
        
        # Check Doppioni (Evitiamo di comprare/vendere 2 volte lo stesso asset)
        for p in portfolio_state["open_positions"]:
            if p['epic'] == real_epic:
                logger.warning(f"AUDIT REJECT: Abbiamo già una posizione aperta su {real_epic}!")
                await publish_audit_action(real_epic, f"{req.direction}", "REJECTED", "Asset già in portafoglio (No averaging up/down)")
                return {"status": "rejected", "reason": "Duplicate Position"}
    else:
        real_epic = req.epic

    # Eccezione "Recovery Mode": Se prob > 90%, ignora il blocco del drawdown -3%
    is_recovery_override = False
    if req.prob is not None and req.prob > 0.90:
        is_recovery_override = True
        logger.info(f"🔥 RECOVERY MODE OVERRIDE ATTIVO per {real_epic} (Prob {req.prob*100:.1f}%)")

    if portfolio_state["is_trading_locked"] and not is_recovery_override:
        logger.warning("AUDIT REJECT: Trading bloccato per la giornata (Take Profit o Max Drawdown).")
        await publish_audit_action(real_epic, f"{req.direction} {req.size_pct}%", "REJECTED", "Trading Locked")
        return {"status": "rejected", "reason": "Trading Locked"}
        
    # Regola 0: Verifica Scaglioni (Position Sizing Dinamico)
    if req.size_pct > 5.0:
        if req.prob is None or not (req.prob > 0.95 or req.prob < 0.05):
            logger.warning(f"AUDIT REJECT: Gemini ha chiesto {req.size_pct}% (Livello 3) ma le condizioni matematiche non lo giustificano (Prob: {req.prob}).")
            await publish_audit_action(real_epic, f"{req.direction} {req.size_pct}%", "REJECTED", "Sizing Limit Exceeded (Livello 3 non autorizzato)")
            return {"status": "rejected", "reason": "Sizing Limit Exceeded"}
    elif req.size_pct > 2.0:
        if req.prob is None or not (req.prob > 0.90 or req.prob < 0.10):
            logger.warning(f"AUDIT REJECT: Gemini ha chiesto {req.size_pct}% (Livello 2) ma le condizioni matematiche non lo giustificano (Prob: {req.prob}).")
            await publish_audit_action(real_epic, f"{req.direction} {req.size_pct}%", "REJECTED", "Sizing Limit Exceeded (Livello 2 non autorizzato)")
            return {"status": "rejected", "reason": "Sizing Limit Exceeded"}

    # Regola 1: Max Position Size (Taglio automatico al 10%)
    final_size = min(req.size_pct, 10.0)
    if final_size < req.size_pct:
        logger.warning(f"AUDIT WARN: Size ridotta da {req.size_pct}% al {final_size}% (Max 10% Rule)")
        
    # Regola 2: Max Leverage Cap (es. max 5x)
    final_leverage = min(req.leverage, 5)
    if final_leverage < req.leverage:
        logger.warning(f"AUDIT WARN: Leva ridotta da {req.leverage}x a {final_leverage}x (Max Cap Rule)")
        
    # Regola 3: Esposizione Massima (50%)
    current_exposure = sum(p['size'] for p in portfolio_state["open_positions"])
    if current_exposure + final_size > 50.0:
        logger.error(f"AUDIT REJECT: Superata esposizione massima del 50%. (Attuale: {current_exposure}%)")
        await publish_audit_action(real_epic, f"{req.direction} {final_size}%", "REJECTED", f"Superata Esposizione Max 50% (Attuale {current_exposure}%)")
        return {"status": "rejected", "reason": "Max Exposure 50% Rule"}
        
    # Approvo l'ordine
    logger.info(f"✅ AUDIT APPROVE: Ordine validato! Esecuzione su Capital.com -> {real_epic} {req.direction} {final_size}% L{final_leverage}x")
    await publish_audit_action(real_epic, f"{req.direction} {final_size}% L{final_leverage}x", "APPROVED", "Risk Checks Passed")
    
    # ESECUZIONE REALE SU CAPITAL.COM
    if api.is_authenticated:
        market_price = api.get_market_price(real_epic)
        margin_info = api.get_margin_info()
        equity = margin_info.get("equity", 0.0)
        
        amount_to_invest = equity * (final_size / 100.0)
        lot_size = (amount_to_invest / market_price) if market_price > 0 else 0.1
        
        logger.info(f"Capital.com: Calcolo Lotti -> Equity: {equity}, Investito: {amount_to_invest}, Prezzo: {market_price} = Size {lot_size} lotti")
        
        min_size = api.get_min_deal_size(real_epic)
        if lot_size < min_size:
            required_margin_for_min_size = (min_size * market_price)
            max_allowed_margin = equity * 0.12 # 12% massimo tollerato (10% + 2% di flessibilità)
            
            if required_margin_for_min_size > max_allowed_margin:
                msg = f"Il broker impone un lotto minimo di {min_size} che richiederebbe {required_margin_for_min_size:.2f}$ di margine. Questo supera il tuo limite di rischio (Max {max_allowed_margin:.2f}$). Ordine scartato."
                logger.error(f"AUDIT REJECT: {msg}")
                await publish_audit_action(real_epic, f"{req.direction}", "REJECTED", msg)
                return {"status": "rejected", "reason": "Min Size Exceeds Risk Limit"}
            else:
                logger.warning(f"Size arrotondata al minimo del broker ({min_size} lotti). Margine richiesto: {required_margin_for_min_size:.2f}$")
                lot_size = min_size
                
        # Piazziamo fisicamente l'ordine
        res = api.place_order(real_epic, req.direction, lot_size)
        if res.get("status") != "success":
            logger.error(f"FALLIMENTO INVIO ORDINE CAPITAL.COM: {res}")
            await publish_audit_action(real_epic, f"{req.direction} {lot_size} lotti", "REJECTED", f"Broker API Error: {res.get('message', 'Errore Sconosciuto')}")
            return {"status": "error", "reason": "Broker API Error"}
        
        # Conferma UI
        await publish_audit_action(real_epic, f"BUY {lot_size} lotti" if req.direction == "BUY" else f"SELL {lot_size} lotti", "SYSTEM", "Ordine piazzato fisicamente su broker.")
        
        # Aggiornamento preventivo locale per evitare race condition sul Max 50% Exposure
        portfolio_state["open_positions"].append({
            "epic": real_epic,
            "direction": req.direction,
            "size": final_size,
            "leverage": final_leverage,
            "pnl_pct": 0.0
        })
        
        return {
            "status": "approved",
            "executed_size_pct": final_size,
            "executed_leverage": final_leverage
        }
    else:
        logger.warning("Capital.com non connesso. Esecuzione simulata (Mock).")
        # Mock salvataggio posizione
        portfolio_state["open_positions"].append({
            "epic": req.epic,
            "direction": req.direction,
            "size": final_size,
            "leverage": final_leverage,
            "pnl_pct": 0.0
        })
    
    # TODO: Logga la decisione finale di Gemini e dell'Auditor sul Database Centrale per l'auto-apprendimento
    
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
            
            # HARD RULE: Global Take Profit 1%
            if portfolio_state["current_pnl_pct"] >= 1.0 and not portfolio_state["is_trading_locked"]:
                logger.info("🏆 OBIETTIVO GIORNALIERO +1% RAGGIUNTO! Chiusura globale e blocco trading.")
                portfolio_state["open_positions"].clear() 
                portfolio_state["is_trading_locked"] = True
                await publish_audit_action("PORTFOLIO", "Chiusura Globale", "SYSTEM", "Obiettivo Giornaliero +1% Raggiunto!")
                
            # HARD RULE: Flexible Drawdown -3%
            if portfolio_state["current_pnl_pct"] <= -3.0 and not portfolio_state["is_trading_locked"]:
                logger.warning("🚨 MAX DRAWDOWN -3% RAGGIUNTO! Protezione capitale attivata. Chiusura globale.")
                portfolio_state["open_positions"].clear()
                portfolio_state["is_trading_locked"] = True
                await publish_audit_action("PORTFOLIO", "Protezione Capitale", "SYSTEM", "Max Drawdown -3% Raggiunto. Chiusura Globale.")
                
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
                r = await aioredis.from_url(REDIS_URL)
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
            r = await aioredis.from_url(REDIS_URL)
            pubsub = r.pubsub()
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
    asyncio.create_task(risk_monitor_loop())
    asyncio.create_task(audit_listener_loop())
