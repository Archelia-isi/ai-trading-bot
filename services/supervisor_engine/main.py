import asyncio
import os
import json
import logging
import redis.asyncio as aioredis
import google.generativeai as genai
from core.database import DatabaseManager

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

async def generate_protocol(epic: str, direction: str, votes_mean: float, pnl: float):
    """(Disattivato) La generazione testuale di Gemini è stata sostituita dalla Cross-Pollination numerica."""
    pass

async def evaluation_loop():
    """Ciclo che verifica se i trade in DB si sono chiusi (gestito in tempo reale dal listener)."""
    logger.info("Avviato Ciclo di Valutazione Trade (Cross-Pollination Numerica)...")
    while True:
        await asyncio.sleep(60)

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
                        pnl = p.get('pnl_pct', 0.0)
                        new_open_epics.add(epic)
                        active_trades_pnl[epic] = pnl # Aggiorna l'ultimo PnL noto
                        
                    # Controlliamo se qualche trade è stato chiuso
                    closed_epics = currently_open_epics - new_open_epics
                    for closed_epic in closed_epics:
                        final_pnl = active_trades_pnl.get(closed_epic, 0.0)
                        logger.info(f"Rilevata chiusura trade su {closed_epic}. PnL Finale: {final_pnl}%")
                        
                        # Cerchiamo nel DB il trade non valutato per questo epic
                        unevaluated = db.get_unevaluated_trades()
                        target_trade = next((t for t in unevaluated if t['epic'] == closed_epic), None)
                        
                        if target_trade:
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
