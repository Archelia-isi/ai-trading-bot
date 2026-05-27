from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline
import torch
import logging
import asyncio
import feedparser
import redis
import json
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FinBERT NLP Microservice (Event-Driven)")

nlp_pipeline = None
redis_client = None

# Feed RSS di base (Azioni, Crypto, Materie prime)
RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL,MSFT,TSLA,BTC-USD,ETH-USD,GC=F,CL=F",
]

class TextRequest(BaseModel):
    text: str

def init_redis():
    global redis_client
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = redis.from_url(redis_url)
        logger.info(f"Connesso a Redis: {redis_url}")
    except Exception as e:
        logger.error(f"Impossibile connettersi a Redis: {e}")

async def news_scanner_loop():
    logger.info("Avviato NLP News Scanner (Event-Driven)...")
    seen_articles = set()
    
    while True:
        if not nlp_pipeline or not redis_client:
            await asyncio.sleep(5)
            continue
            
        try:
            for feed_url in RSS_FEEDS:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    article_id = entry.link
                    if article_id in seen_articles:
                        continue
                        
                    title = entry.title
                    seen_articles.add(article_id)
                    
                    # Sentiment Analysis
                    results = nlp_pipeline(title)
                    if len(results) > 0:
                        res = results[0]
                        score = res['score']
                        label = res['label'].upper()
                        
                        # Se è una NOTIZIA BOMBA (> 0.8 confidenza e non neutrale)
                        if score >= 0.8 and label != "NEUTRAL":
                            logger.info(f"🚨 NOTIZIA BOMBA TROVATA: {title} [{label} {score}]")
                            
                            # Estraiamo il probabile Ticker (molto grezzo per l'esempio, di base invia la news)
                            payload = {
                                "title": title,
                                "label": label,
                                "score": float(score),
                                "link": entry.link,
                                "source": "YahooFinanceRSS"
                            }
                            
                            # Pubblica sul canale Redis per l'Analista Matematico
                            redis_client.publish("news_alerts", json.dumps(payload))
                            
        except Exception as e:
            logger.error(f"Errore nello scanner RSS: {e}")
            
        # Pulisci cache per evitare memory leaks
        if len(seen_articles) > 5000:
            seen_articles.clear()
            
        # Aspetta 60 secondi prima del prossimo giro
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    global nlp_pipeline
    init_redis()
    logger.info("Avvio caricamento FinBERT in RAM...")
    try:
        device = 0 if torch.cuda.is_available() else -1
        nlp_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=device)
        logger.info("FinBERT caricato con successo e pronto.")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
        
    # Avvia il loop in background
    asyncio.create_task(news_scanner_loop())

@app.post("/analyze")
def analyze_sentiment(request: TextRequest):
    # Endpoint classico per test manuali
    if not nlp_pipeline:
        raise HTTPException(status_code=503, detail="Model is still loading or failed to load")
    
    try:
        results = nlp_pipeline(request.text)
        if len(results) > 0:
            result = results[0]
            return {"label": result['label'].upper(), "score": float(result['score'])}
        return {"label": "NEUTRAL", "score": 0.5}
    except Exception as e:
        logger.error(f"Errore inferenza: {e}")
        raise HTTPException(status_code=500, detail=str(e))
