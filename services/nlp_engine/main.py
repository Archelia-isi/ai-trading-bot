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

import re

# Feed RSS Globali (Reddit, Google News, Yahoo)
RSS_FEEDS = [
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US", "name": "YahooFinance Global"},
    {"url": "https://news.google.com/rss/search?q=stock+market+breaking+news", "name": "GoogleNews Markets"},
    {"url": "https://news.google.com/rss/search?q=cryptocurrency+breaking+news", "name": "GoogleNews Crypto"},
    {"url": "https://www.reddit.com/r/CryptoCurrency/new/.rss", "name": "Reddit CryptoCurrency"},
    {"url": "https://www.reddit.com/r/WallStreetBets/new/.rss", "name": "Reddit WallStreetBets"}
]

# --- TRADUTTORE SLANG REDDIT ---
SLANG_MAP = {
    "to the moon": "highly positive outlook",
    "hodl": "hold long term confidently",
    "rekt": "destroyed financially",
    "bullish": "optimistic and positive",
    "bearish": "pessimistic and negative",
    "pump": "rapid price increase",
    "dump": "rapid price decrease",
    "fud": "fear uncertainty doubt negative",
    "diamond hands": "strong confident hold positive",
    "paper hands": "weak early selling negative"
}

def translate_slang(text: str) -> str:
    lower_text = text.lower()
    for slang, translation in SLANG_MAP.items():
        if slang in lower_text:
            # Sostituzione case-insensitive grezza per performance
            text = re.sub(re.escape(slang), translation, text, flags=re.IGNORECASE)
    return text

# --- NER DINAMICA (Named Entity Recognition) ---
TICKER_MAP = {
    "apple": "AAPL", "iphone": "AAPL", "macbook": "AAPL",
    "microsoft": "MSFT", "windows": "MSFT",
    "tesla": "TSLA", "musk": "TSLA",
    "amazon": "AMZN", "bezos": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL",
    "nvidia": "NVDA", "geforce": "NVDA",
    "meta": "META", "facebook": "META", "zuckerberg": "META",
    "bitcoin": "BTCUSD", "btc": "BTCUSD",
    "ethereum": "ETHUSD", "eth": "ETHUSD",
    "gold": "GOLD", "oro": "GOLD",
    "oil": "OIL_BRENT", "petrolio": "OIL_BRENT", "exxon": "OIL_BRENT", "exxonmobil": "OIL_BRENT",
    "rivian": "RIVN", "palantir": "PLTR", "netflix": "NFLX"
}

def extract_ticker(text: str) -> str:
    # Cerca Ticker formali (es. AAPL o $AAPL)
    match = re.search(r'\$?([A-Z]{3,5})\b', text)
    if match and match.group(1) not in ["THE", "AND", "FOR", "NEW", "INC", "CORP"]:
        # Se trova una parola tutta in maiuscolo probabile Ticker (molto base)
        pass # Disabilitato per evitare troppi falsi positivi, usiamo il dizionario per sicurezza
        
    lower_text = text.lower()
    for keyword, ticker in TICKER_MAP.items():
        if re.search(r'\b' + keyword + r'\b', lower_text):
            return ticker
    return None

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

async def scan_feed(feed_info, seen_articles):
    source_name = feed_info['name']
    feed_url = feed_info['url']
    try:
        # I/O Bound: run_in_executor per non bloccare l'event loop
        feed = await asyncio.to_thread(feedparser.parse, feed_url)
        for entry in feed.entries:
            article_id = entry.link
            if article_id in seen_articles:
                continue
                
            seen_articles.add(article_id)
            title = entry.title
            
            # 1. Traduzione Slang (se fonte Reddit)
            if "reddit" in source_name.lower():
                title = translate_slang(title)
                
            # 2. NER Extraction "A Mano Libera"
            epic = extract_ticker(title)
            if not epic:
                # Il Segugio ignora le notizie dove non individua chiaramente l'azienda
                continue
                
            # 3. Sentiment Analysis FinBERT (Usa in automatico la potenza multicore di PyTorch)
            results = nlp_pipeline(title)
            if len(results) > 0:
                res = results[0]
                score = res['score']
                label = res['label'].upper()
                
                # Soglia di confidenza al 75% per evitare rumore
                if score >= 0.75 and label != "NEUTRAL":
                    logger.info(f"[{source_name}] 🚨 BOMBA SU {epic}: {title} [{label} {score}]")
                    
                    payload = {
                        "epic": epic,
                        "title": title,
                        "label": label,
                        "score": float(score),
                        "link": entry.link,
                        "source": source_name
                    }
                    
                    redis_client.publish("news_alerts", json.dumps(payload))
                    
    except Exception as e:
        logger.error(f"Errore nell'Agente Segugio {source_name}: {e}")

async def news_scanner_loop():
    logger.info("Avviato Segugio Globale Multicore (Reddit, Google News, Yahoo)...")
    seen_articles = set()
    
    while True:
        if not nlp_pipeline or not redis_client:
            await asyncio.sleep(5)
            continue
            
        try:
            # Sguinzaglia molteplici "Agenti" in parallelo
            tasks = [scan_feed(feed, seen_articles) for feed in RSS_FEEDS]
            await asyncio.gather(*tasks)
            
        except Exception as e:
            logger.error(f"Errore nel main loop del Segugio: {e}")
            
        # Pulisci cache per evitare memory leaks
        if len(seen_articles) > 10000:
            seen_articles.clear()
            
        # Pausa breve per reattività massima
        await asyncio.sleep(30)

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
