import asyncio
import redis.asyncio as aioredis
import json
import os
import logging
import google.generativeai as genai
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://localhost:8002")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

async def process_alert(data, model):
    epic = data.get('epic')
    action = data.get('action_suggested')
    prob = data.get('xgboost_prob')
    news = data.get('news_title')
    
    logger.info(f"Ricevuto Segnale su {epic} per {action}! Interpello Gemini in parallelo...")
    
    if not model:
        logger.error("Gemini non configurato, impossibile decidere.")
        return
        
    prompt = f"""
Sei il Portfolio Manager di un Hedge Fund Quantitativo che opera con CFD.
Hai il potere di andare LONG (comprare) o SHORT (vendere allo scoperto) su qualsiasi asset per trarre profitto sia dai rialzi che dai crolli.
Hai appena ricevuto un allarme dai tuoi motori di analisi per l'asset: {epic}.
Azione suggerita dall'Algoritmo: {action} (BUY = Vai Long, SELL = Vai Short)
Probabilità di successo (XGBoost): {prob*100:.2f}%
Ultima notizia rilevante: "{news}"

In base a questi dati, decidi se ESEGUIRE l'ordine, la SIZE (max 10% del capitale) e la LEVA (es. 1, 2, 5).
Se l'azione suggerita è SELL e la notizia è negativa, apri una posizione SHORT (decision: "SELL") per guadagnare dal crollo.
Se la notizia contiene "Occasione Tecnica Pura", significa che l'algoritmo ha individuato un pattern matematico fortissimo: in tal caso FIDATI dei numeri ed esegui sempre il trade (BUY o SELL) senza cercare conferme esterne!
Rispondi ESATTAMENTE in questo formato JSON (nient'altro):
{{"decision": "BUY" | "SELL" | "HOLD", "size_pct": float, "leverage": int, "reasoning": "string"}}
    """
    
    try:
        # Esecuzione in pool di thread paralleli per non bloccare il loop
        response = await asyncio.to_thread(model.generate_content, prompt)
        testo_gemini = response.text.strip().replace('```json', '').replace('```', '')
        decision_data = json.loads(testo_gemini)
        
        logger.info(f"Decisione Gemini: {decision_data['decision']} su {epic}. Motivazione: {decision_data['reasoning']}")
        
        # Invia messaggio alla Dashboard via Redis
        pub_payload = {
            "epic": epic,
            "decision": decision_data['decision'],
            "size_pct": decision_data['size_pct'],
            "leverage": decision_data['leverage'],
            "reasoning": decision_data['reasoning']
        }
        try:
            r = await aioredis.from_url(REDIS_URL)
            await r.publish("gemini_decisions", json.dumps(pub_payload))
        except Exception as red_err:
            logger.error(f"Errore pubblicazione Redis: {red_err}")
            
        if decision_data['decision'] in ['BUY', 'SELL']:
            payload_to_audit = {
                "epic": epic,
                "direction": decision_data['decision'],
                "size_pct": decision_data['size_pct'],
                "leverage": decision_data['leverage'],
                "reasoning": decision_data['reasoning'],
                "news": news,
                "prob": prob
            }
            logger.info(f"Invio proposta di trade all'Auditor: {payload_to_audit}")
            
            try:
                audit_resp = await asyncio.to_thread(
                    requests.post, 
                    f"{AUDIT_SERVICE_URL}/audit_order", 
                    json=payload_to_audit,
                    timeout=10
                )
                logger.info(f"Risposta Auditor: {audit_resp.json()}")
            except Exception as req_err:
                logger.error(f"Errore comunicazione con Auditor: {req_err}")
            
    except Exception as e:
        logger.error(f"Errore durante l'interrogazione di Gemini su {epic}: {e}")

async def portfolio_manager_loop():
    logger.info("Avviato Portfolio Manager Worker (Ascolto Allarmi Parallelo)...")
    
    try:
        model = genai.GenerativeModel('gemini-1.5-pro')
    except Exception as e:
        logger.error(f"Errore caricamento Gemini: {e}")
        model = None

    while True:
        try:
            r = await aioredis.from_url(REDIS_URL)
            pubsub = r.pubsub()
            await pubsub.subscribe("portfolio_alerts")
            
            logger.info("In ascolto sul canale 'portfolio_alerts'...")
            
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    # Crea un task asincrono parallelo per processare questa singola richiesta
                    # in questo modo può processarne 20 contemporaneamente!
                    asyncio.create_task(process_alert(data, model))
                        
        except Exception as e:
            logger.error(f"Errore connessione Redis nel Portfolio Manager: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(portfolio_manager_loop())
