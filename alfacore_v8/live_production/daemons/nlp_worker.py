import os
import time
import redis
import requests
from dotenv import load_dotenv
from transformers import pipeline

load_dotenv()

print("Avvio Demone NLP (HuggingFace CPU-Bound)...")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    print("Connessione a Redis stabilita per il Worker NLP.")
except Exception as e:
    print(f"Errore critico di connessione a Redis: {e}")
    raise e

nlp_pipe = pipeline("sentiment-analysis", model="distilbert/distilbert-base-uncased-finetuned-sst-2-english", device=-1)

EMA_SPAN = 14
ALPHA = 2 / (EMA_SPAN + 1)

if not r.exists('live_crypto_sentiment'):
    r.set('live_crypto_sentiment', 0.0)
if not r.exists('crypto_bars_since_news'):
    r.set('crypto_bars_since_news', 0)

def scarica_notizie():
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        return []
    try:
        res = requests.get(f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&kind=news", timeout=10)
        res.raise_for_status()
        return [post['title'] for post in res.json().get('results', [])[:5]]
    except Exception as e:
        print(f"Errore durante lo scaricamento delle notizie: {e}")
        return []

while True:
    try:
        titoli = scarica_notizie()
        impatto_grezzo = 0.0
        
        if titoli:
            risultati = nlp_pipe(titoli)
            for res in risultati:
                score = res['score'] if res['label'] == 'POSITIVE' else -res['score']
                impatto_grezzo += score
                
        ema_precedente = float(r.get('live_crypto_sentiment') or 0.0)
        nuova_ema = (impatto_grezzo * ALPHA) + (ema_precedente * (1 - ALPHA))
        
        r.set('live_crypto_sentiment', nuova_ema)
        
        if impatto_grezzo != 0.0:
            r.set('crypto_bars_since_news', 0)
        else:
            r.incr('crypto_bars_since_news')
            
        contatore_minuti = r.get('crypto_bars_since_news')
        print(f"[Sistema NLP] Impatto: {impatto_grezzo:.2f} | EMA: {nuova_ema:.3f} | Minuti dall'ultima news: {contatore_minuti}")
        
    except Exception as e:
        print(f"Errore imprevisto nel ciclo NLP: {e}. Attendo il prossimo ciclo.")
        
    time.sleep(60)
