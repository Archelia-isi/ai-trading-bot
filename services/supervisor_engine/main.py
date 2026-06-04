import asyncio
import os
import json
import logging
import redis.asyncio as aioredis
import google.generativeai as genai
from core.database import DatabaseManager
from core.capital_api import CapitalComAPI
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    
db = DatabaseManager()

# Memoria temporanea per collegare la genesi del trade
temp_signals = {}    # epic -> {news, prob}
temp_decisions = {}  # epic -> {reasoning}
active_trades_pnl = {} # epic -> last known pnl

api = CapitalComAPI()
api.authenticate()

async def generate_protocol(epic: str, direction: str, votes_mean: float, pnl: float):
    """(Disattivato) La generazione testuale di Gemini è stata sostituita dalla Cross-Pollination numerica."""
    pass

async def evaluation_loop():
    """Ciclo che agisce da 'Esattore del Day Trading' per punire stagnazione, avidità e testardaggine."""
    logger.info("Avviato Esattore del Day Trading (Valutazione Attiva dei Trade Aperti)...")
    while True:
        await asyncio.sleep(300) # Controlla ogni 5 minuti
        
        try:
            unevaluated = db.get_unevaluated_trades()
            if not unevaluated:
                continue
                
            now = datetime.now(timezone.utc)
            
            for t in unevaluated:
                epic = t['epic']
                trade_id = t['id']
                
                # Se non abbiamo il PnL corrente (non è nelle posizioni aperte), ignoriamo per ora
                if epic not in active_trades_pnl:
                    continue
                    
                current_pnl = active_trades_pnl[epic]
                
                # opened_at potrebbe essere naive o timezone-aware.
                # Assumiamo sia UTC dal DB.
                opened_at = t['opened_at']
                if opened_at.tzinfo is None:
                    opened_at = opened_at.replace(tzinfo=timezone.utc)
                    
                hours_alive = (now - opened_at).total_seconds() / 3600.0
                
                penalty_pnl = None
                reason = ""
                
                # Regola 6: Rischio Gap Dinamico (Meno di 30 min alla chiusura)
                is_crypto = any(c in epic for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"])
                if not is_crypto:
                    if api.is_market_closing_soon(epic, threshold_minutes=30):
                        penalty_pnl = -5.0
                        reason = "Tassa Overnight (Rischio Gap a mercato chiuso)"
                
                # Se non ha scattato il rischio Gap, controlliamo se ha superato le 4 ore (Time Decay)
                if penalty_pnl is None and hours_alive >= 4.0:
                    if -1.0 <= current_pnl <= 1.0:
                        penalty_pnl = -5.0
                        reason = "Stagnazione Piatta (Sprecato margine per > 4 ore)"
                    elif -2.0 <= current_pnl < -1.0:
                        penalty_pnl = -8.0
                        reason = "Sanguinamento Lento (Hold in perdita per > 4 ore)"
                    elif 1.0 < current_pnl <= 2.0:
                        penalty_pnl = -2.0
                        reason = "Profitto Lento (Mancato Incasso, troppo tempo per poco gain)"
                    elif current_pnl > 2.0:
                        penalty_pnl = -5.0
                        reason = "Avidità Estrema (Oltre +2% in 4 ore senza vendere)"
                    elif current_pnl < -2.0:
                        penalty_pnl = -10.0
                        reason = "Testardaggine Suicida (Oltre -2% in 4 ore senza tagliare)"
                        
                if penalty_pnl is not None:
                    logger.warning(f"⚖️ [ESATTORE] Trade {trade_id} ({epic}) sanzionato! Motivo: {reason} | PnL reale: {current_pnl:.2f}% | PnL virtuale: {penalty_pnl}%")
                    db.mark_trade_evaluated(trade_id, penalty_pnl)
                    # Una volta sanzionato e valutato, non verrà più addestrato stanotte per altri motivi.
                    
        except Exception as e:
            logger.error(f"Errore nell'Esattore del Day Trading: {e}")

async def redis_listener():
    logger.info("Avviato Supervisore Silenzioso (Redis Listener)...")
    try:
        r = await aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe("supervisor_trade_genesis", "portfolio_status")
        
        # Inizializziamo set per sapere cosa è aperto
        currently_open_epics = set()
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                channel = message['channel'].decode('utf-8')
                data = json.loads(message['data'])
                
                if channel == 'supervisor_trade_genesis':
                    epic = data.get('epic')
                    direction = data.get('direction', 'BUY')
                    source = data.get('source', 'UNKNOWN')
                    votes_mean = data.get('votes_mean', 0.0)
                    size = data.get('size', 0.0)
                    price = data.get('price', 0.0)
                    
                    # Logga numericamente nel DB la nascita del trade
                    # Riutilizziamo la tabella existende passando i dati numerici mappati
                    db.log_trade_genesis(
                        epic=epic, 
                        direction=direction, 
                        news_title=source, # Usiamo la colonna news per la source
                        xgboost_prob=votes_mean, # Usiamo prob per la media dei voti
                        gemini_reasoning=f"Voto Pesato: {votes_mean:.2f}",
                        executed_size=size, 
                        leverage=1
                    )
                    logger.info(f"🧬 Genesi Trade Registrata: {direction} su {epic} (Consiglio D'Amministrazione - Media: {votes_mean:.2f})")
                    
                elif channel == 'portfolio_status':
                    # Analizziamo le posizioni aperte per capire chiusure e PnL
                    open_positions = data.get('open_positions', [])
                    new_open_epics = set()
                    
                    for p in open_positions:
                        epic = p.get('epic')
                        # Salviamo l'asset_move_pct (reale movimento di mercato senza leva) per l'Esattore
                        # Se non esiste, fallback sul pnl_pct
                        pnl = p.get('asset_move_pct', p.get('pnl_pct', 0.0))
                        new_open_epics.add(epic)
                        active_trades_pnl[epic] = pnl # Aggiorna l'ultimo PnL noto
                        
                    # PROTEZIONE: Se improvvisamente i trade scendono a zero ma ce n'erano tanti,
                    # potrebbe essere un calo di rete. Non chiudiamo l'universo senza conferma.
                    if len(new_open_epics) == 0 and len(currently_open_epics) > 0:
                        logger.warning("ATTENZIONE: Ricevuto array vuoto da Redis ma avevamo posizioni aperte. Potrebbe essere una disconnessione di Capital.com. Attendo conferme.")
                        await asyncio.sleep(5)
                        continue
                        
                    # Controlliamo se qualche trade è stato chiuso
                    closed_epics = currently_open_epics - new_open_epics
                    for closed_epic in closed_epics:
                        final_pnl = active_trades_pnl.get(closed_epic, 0.0)
                        logger.info(f"Rilevata chiusura trade su {closed_epic}. PnL Finale: {final_pnl}%")
                        
                        # Cerchiamo nel DB tutti i trade non valutati per questo epic (Accumuli)
                        unevaluated = db.get_unevaluated_trades()
                        target_trades = [t for t in unevaluated if t['epic'] == closed_epic]
                        
                        for target_trade in target_trades:
                            db.mark_trade_evaluated(target_trade['id'], final_pnl)
                            # Generiamo il protocollo di apprendimento in background
                            asyncio.create_task(
                                generate_protocol(
                                    closed_epic, 
                                    target_trade['direction'], 
                                    target_trade['news_title'],
                                    target_trade['xgboost_prob'],
                                    target_trade['gemini_reasoning'],
                                    final_pnl
                                )
                            )
                            
                    currently_open_epics = new_open_epics

    except Exception as e:
        logger.error(f"Errore nel Listener del Supervisore: {e}")

async def main():
    await asyncio.gather(
        redis_listener(),
        evaluation_loop()
    )

if __name__ == "__main__":
    asyncio.run(main())
