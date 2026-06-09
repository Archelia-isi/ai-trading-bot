import os
import time
import redis
import requests
from transformers import pipeline

print("🧠 Avvio NLP Worker Daemon (HuggingFace)...")

# Inizializza Redis
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()
    print("✅ Connesso a Redis per NLP Worker")
except Exception as e:
    print(f"❌ Impossibile connettersi a Redis ({redis_url}): {e}")
    exit(1)

# Inizializza Pipeline HF (Ottimizzata CPU per container generici)
model_name = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
nlp_pipe = pipeline("sentiment-analysis", model=model_name, device=-1)

EMA_SPAN = 14
alpha = 2 / (EMA_SPAN + 1)

# Inizializza stato Redis se vuoto
if not r.exists('live_crypto_sentiment'): r.set('live_crypto_sentiment', 0.0)
if not r.exists('crypto_bars_since_news'): r.set('crypto_bars_since_news', 0)

def fetch_live_news():
    """Simula una chiamata API a CryptoPanic o simile. Per produzione vera inserire API Key"""
    api_key = os.getenv("CRYPTOPANIC_API_KEY")
    if not api_key:
        return [] # Ritorna vuoto se non c'e' key
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&kind=news"
        res = requests.get(url, timeout=10)
        return [post['title'] for post in res.json().get('results', [])[:5]]
    except:
        return []

while True:
    try:
        news_titles = fetch_live_news()
        
        raw_shock = 0.0
        if news_titles:
            results = nlp_pipe(news_titles)
            for res in results:
                score = res['score'] if res['label'] == 'POSITIVE' else -res['score']
                raw_shock += score
                
        # Calcolo EMA
        prev_ema = float(r.get('live_crypto_sentiment') or 0.0)
        new_ema = (raw_shock * alpha) + (prev_ema * (1 - alpha))
        r.set('live_crypto_sentiment', new_ema)
        
        # Gestione sparsità temporale
        if raw_shock != 0.0:
            r.set('crypto_bars_since_news', 0)
        else:
            r.incr('crypto_bars_since_news')
            
        print(f"📊 [NLP] Shock: {raw_shock:.2f} | EMA: {new_ema:.3f} | Bars: {r.get('crypto_bars_since_news')}")
        
    except Exception as e:
        print(f"⚠️ Errore NLP Worker Loop: {e}")
        
    time.sleep(60) # Gira 1 volta al minuto per non esaurire rate limits
