import asyncio
import redis.asyncio as aioredis
import json
import os
import logging
import google.generativeai as genai
import requests
from core.database import DatabaseManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AUDIT_SERVICE_URL = os.getenv("AUDIT_SERVICE_URL", "http://localhost:8002")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

db = DatabaseManager()

async def process_alert(data, model):
    epic = data.get('epic')
    action = data.get('action_suggested')
    prob = data.get('xgboost_prob')
    news = data.get('news_title')
    
    logger.info(f"Ricevuto Segnale su {epic} per {action}! Interpello Gemini in parallelo...")
    
    if not model:
        logger.error("Gemini non configurato, impossibile decidere.")
        return
        
    # Estrai i protocolli attivi dal DB
    active_protocols = db.get_active_protocols()
    protocols_text = ""
    if active_protocols:
        for i, p in enumerate(active_protocols):
            protocols_text += f"{i+1}. [Per {p['epic'] if p['epic'] else 'TUTTI'}]: {p['protocol_text']}\n"
    else:
        protocols_text = "Nessuna direttiva aggiuntiva al momento."
        

    async def get_cfg(k, d):
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            v = await r.get(f"config:{k}")
            await r.close()
            return float(v) if v is not None else d
        except: return d

    s1_min = await get_cfg("scaglione_1_size_min", 0.5)
    s1_max = await get_cfg("scaglione_1_size_max", 2.0)
    s1_l = await get_cfg("scaglione_1_prob_long", 0.75)
    s1_s = await get_cfg("scaglione_1_prob_short", 0.25)

    s2_min = await get_cfg("scaglione_2_size_min", 3.0)
    s2_max = await get_cfg("scaglione_2_size_max", 5.0)
    s2_l = await get_cfg("scaglione_2_prob_long", 0.90)
    s2_s = await get_cfg("scaglione_2_prob_short", 0.10)

    s3_min = await get_cfg("scaglione_3_size_min", 8.0)
    s3_max = await get_cfg("scaglione_3_size_max", 10.0)
    s3_l = await get_cfg("scaglione_3_prob_long", 0.95)
    s3_s = await get_cfg("scaglione_3_prob_short", 0.05)


    prompt = f"""
Sei il Portfolio Manager di un Hedge Fund Quantitativo che opera con CFD.
Hai il potere di andare LONG (comprare) o SHORT (vendere allo scoperto) su qualsiasi asset per trarre profitto sia dai rialzi che dai crolli.
Hai appena ricevuto un allarme dai tuoi motori di analisi per l'asset: {epic}.
Azione suggerita dall'Algoritmo: {action} (BUY = Vai Long, SELL = Vai Short)
Probabilità di successo (XGBoost): {prob*100:.2f}%
Ultima notizia rilevante: "{news}"

In base a questi dati, decidi se ESEGUIRE l'ordine, la SIZE e la LEVA (es. 1, 2, 5).
Se l'azione suggerita è SELL, apri una posizione SHORT (decision: "SELL") per guadagnare dal crollo.

DEVI APPLICARE RIGIDAMENTE QUESTO SISTEMA DI ALLOCAZIONE A SCAGLIONI:
1. **Livello 1 - Ricognizione (Size tra {s1_min}% e {s1_max}%)**: Da usare quando la probabilità è tra {s1_l*100}% e {s2_l*100}% (o tra {s1_s*100}% e {s2_s*100}% per gli SHORT). Frammenta il rischio!
2. **Livello 2 - Convinzione Forte (Size tra {s2_min}% e {s2_max}%)**: Da usare SOLO se la probabilità è >= {s2_l*100}% (o <= {s2_s*100}% per gli SHORT) E c'è una chiara conferma dalla notizia.
3. **Livello 3 - La "Bomba" (Size tra {s3_min}% e {s3_max}%)**: Da usare SOLO ED ESCLUSIVAMENTE se la probabilità è ESTREMA (>= {s3_l*100}% o <= {s3_s*100}%).

Nella motivazione ("reasoning"), dichiara SEMPRE quale Scaglione hai scelto e perché.

### DIRETTIVE DEL SUPERVISORE (REGOLE DI AUTO-APPRENDIMENTO)
Il tuo supervisore ha analizzato i tuoi errori e successi passati e ti impone di rispettare assolutamente le seguenti regole aggiuntive:
{protocols_text}

Rispondi ESATTAMENTE in questo formato JSON (nient'altro):
{{"decision": "BUY" | "SELL" | "HOLD", "size_pct": float, "leverage": int, "reasoning": "string"}}
    """
    
    try:
        # Retry logic per limiti API (429 Resource Exhausted)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await asyncio.to_thread(
                    model.generate_content, 
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                testo_gemini = response.text.strip()
                break
            except Exception as api_err:
                if "429" in str(api_err) or "quota" in str(api_err).lower():
                    if attempt < max_retries - 1:
                        await asyncio.sleep(10 * (attempt + 1))
                        continue
                raise api_err
                
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
                # Usa Redis al posto di HTTP per l'Auditor (resiliente su container separati)
                r = await aioredis.from_url(REDIS_URL)
                await r.publish("audit_requests", json.dumps(payload_to_audit))
                logger.info("Messaggio inviato con successo ad Audit via Redis.")
            except Exception as req_err:
                logger.error(f"Errore pubblicazione richiesta Audit via Redis: {req_err}")
            
    except Exception as e:
        logger.error(f"Errore durante l'interrogazione di Gemini su {epic}: {e}")

async def portfolio_manager_loop():
    logger.info("Avviato Portfolio Manager Worker (Ascolto Allarmi Parallelo)...")
    
    try:
        # Il modello Pro restituisce 404 in fase di generateContent per limitazioni API.
        # Passiamo direttamente a Flash che è fulmineo, universale e supporta l'output JSON nativo.
        model = genai.GenerativeModel('gemini-3.1-pro-preview')
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
