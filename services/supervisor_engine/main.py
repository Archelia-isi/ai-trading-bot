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

async def generate_protocol(epic: str, direction: str, news: str, prob: float, reasoning: str, pnl: float):
    """Genera un protocollo di apprendimento usando Gemini."""
    if not GEMINI_API_KEY:
        return
        
    outcome_str = "SUCCESSO (Profitto)" if pnl > 0 else "FALLIMENTO (Perdita)"
    
    prompt = f"""
Sei il Supervisore Capo (Analista Esterno) di un Hedge Fund Quantitativo.
Il tuo compito è analizzare le decisioni passate delle tue IA subordinate e creare regole ferree (Protocolli) per migliorare le performance future.

Dettagli del Trade Appena Chiuso:
- Asset: {epic}
- Direzione Scelta: {direction}
- Notizia Iniziale: "{news}"
- Probabilità Calcolata (XGBoost): {prob*100:.2f}%
- Ragionamento del Manager (Gemini): "{reasoning}"
- ESITO FINALE: {outcome_str} ({pnl:.2f}%)

Se l'esito è stato un SUCCESSO, scrivi una breve regola che incoraggi questo tipo di setup.
Se l'esito è stato un FALLIMENTO, scrivi una regola correttiva CRITICA per evitare di ripetere questo errore.
La tua risposta diventerà un pezzo del "System Prompt" del Manager per il futuro.

Rispondi SOLO con il testo della regola (massimo 2-3 frasi), senza commenti o saluti. Esempio: "Se la notizia riguarda l'energia ma la probabilità è sotto il 40%, dimezza la size."
"""
    try:
        model = genai.GenerativeModel('gemini-3.1-pro-preview')
        response = await asyncio.to_thread(model.generate_content, prompt)
        protocol_text = response.text.strip()
        logger.info(f"🧠 Nuovo Protocollo Generato per {epic}: {protocol_text}")
        
        # Salva nel DB
        db.save_ai_protocol(protocol_text, epic)
    except Exception as e:
        logger.error(f"Errore durante la generazione del protocollo AI: {e}")

async def evaluation_loop():
    """Ciclo che verifica se i trade in DB si sono chiusi e genera i protocolli."""
    logger.info("Avviato Ciclo di Valutazione Trade (Self-Learning)...")
    while True:
        try:
            unevaluated = db.get_unevaluated_trades()
            for trade in unevaluated:
                epic = trade['epic']
                trade_id = trade['id']
                
                # Se il trade era tra quelli attivi, ma ora non lo è più, significa che si è chiuso!
                # Nota: Questo check dipende dal fatto che il redis_listener continui ad aggiornare active_trades_pnl
                # Se active_trades_pnl ha un PNL ma il trade non è nel payload 'portfolio_status' più recente, si è chiuso.
                # Per semplificare in modo robusto: se lo troviamo in active_trades_pnl e ha un PNL, lo teniamo aggiornato.
                # Il trigger di "chiusura" lo faremo direttamente nel listener di portfolio_status per essere realtime!
                pass 
                
        except Exception as e:
            logger.error(f"Errore nell'evaluation loop: {e}")
        
        await asyncio.sleep(60)

async def redis_listener():
    logger.info("Avviato Supervisore Silenzioso (Redis Listener)...")
    try:
        r = await aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe("news_alerts", "portfolio_alerts", "gemini_decisions", "audit_actions", "portfolio_status")
        
        # Inizializziamo set per sapere cosa è aperto
        currently_open_epics = set()
        
        async for message in pubsub.listen():
            if message['type'] == 'message':
                channel = message['channel'].decode('utf-8')
                data = json.loads(message['data'])
                
                if channel == 'portfolio_alerts':
                    epic = data.get('epic')
                    temp_signals[epic] = {
                        "news": data.get('news_title', ''),
                        "prob": data.get('xgboost_prob', 0.0)
                    }
                
                elif channel == 'gemini_decisions':
                    epic = data.get('epic')
                    temp_decisions[epic] = {
                        "reasoning": data.get('reasoning', ''),
                        "decision": data.get('decision', 'HOLD')
                    }
                    
                elif channel == 'audit_actions':
                    status = data.get('status')
                    if status == 'APPROVED':
                        # Il trade è stato eseguito sul mercato. Cuciamo i dati.
                        epic = data.get('epic')
                        sig = temp_signals.get(epic, {})
                        dec = temp_decisions.get(epic, {})
                        
                        direction = dec.get('decision', 'BUY')
                        news = sig.get('news', 'N/A')
                        prob = sig.get('prob', 0.0)
                        reasoning = dec.get('reasoning', 'N/A')
                        size = 0.0 # Potremmo estrarla, ma va bene mockata per ora
                        leverage = 1
                        
                        db.log_trade_genesis(epic, direction, news, prob, reasoning, size, leverage)
                        
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
