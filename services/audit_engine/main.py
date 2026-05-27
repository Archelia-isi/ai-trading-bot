from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio
import logging
import os
import requests
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Audit & Risk Management Engine")

# Stato globale fittizio del portafoglio (In un sistema reale, legge da DB o Broker)
portfolio_state = {
    "total_capital": 10000.0,
    "daily_start_capital": 10000.0,
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
    
    # Eccezione "Recovery Mode": Se prob > 90%, ignora il blocco del drawdown -3%
    is_recovery_override = False
    if req.prob is not None and req.prob > 0.90:
        is_recovery_override = True
        logger.info(f"🔥 RECOVERY MODE OVERRIDE ATTIVO per {req.epic} (Prob {req.prob*100:.1f}%)")

    if portfolio_state["is_trading_locked"] and not is_recovery_override:
        logger.warning("AUDIT REJECT: Trading bloccato per la giornata (Take Profit o Max Drawdown).")
        return {"status": "rejected", "reason": "Trading Locked"}
        
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
        return {"status": "rejected", "reason": "Max Exposure 50% Rule"}
        
    # Approvo l'ordine
    logger.info(f"✅ AUDIT APPROVE: Ordine validato! Esecuzione su Capital.com -> {req.epic} {req.direction} {final_size}% L{final_leverage}x")
    
    # Mock salvataggio posizione
    portfolio_state["open_positions"].append({
        "epic": req.epic,
        "direction": req.direction,
        "size": final_size,
        "leverage": final_leverage,
        "pnl_pct": 0.0 # da aggiornare in tempo reale
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
            # 1. Calcolo PnL Globale Giornaliero (Mock - In realtà calcolato dai prezzi in tempo reale)
            portfolio_state["current_pnl_pct"] = sum(p['pnl_pct'] for p in portfolio_state["open_positions"])
            
            # HARD RULE: Global Take Profit 1%
            if portfolio_state["current_pnl_pct"] >= 1.0 and not portfolio_state["is_trading_locked"]:
                logger.info("🏆 OBIETTIVO GIORNALIERO +1% RAGGIUNTO! Chiusura globale e blocco trading.")
                portfolio_state["open_positions"].clear() 
                portfolio_state["is_trading_locked"] = True
                
            # HARD RULE: Flexible Drawdown -3%
            if portfolio_state["current_pnl_pct"] <= -3.0 and not portfolio_state["is_trading_locked"]:
                logger.warning("🚨 MAX DRAWDOWN -3% RAGGIUNTO! Protezione capitale attivata. Chiusura globale.")
                portfolio_state["open_positions"].clear()
                portfolio_state["is_trading_locked"] = True
                
            # HARD RULE: Time Window Lock (Si attiva a 30 min dalla chiusura di Wall Street/Europa)
            # HARD RULE: Flash Crash Kill Switch e Dynamic ATR (Richiede interrogazione prezzi)
                
            await asyncio.sleep(5) # Controlla il rischio ogni 5 secondi!
            
        except Exception as e:
            logger.error(f"Errore loop rischio: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(risk_monitor_loop())
