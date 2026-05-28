from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
import logging
import asyncio
import redis.asyncio as aioredis
import json
import os
# --- FIX LIMITI HARDWARE LINUX ---
# Evita che XGBoost generi migliaia di thread (Resource temporarily unavailable)
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

import requests
import numpy as np
import yfinance as yf
from capital_api import CapitalComAPI
from data_rotator import MultiProviderAPI
from datetime import datetime
import pytz
import time
import concurrent.futures

# --- PARTIZIONAMENTO RIGIDO 24 vCPU ---
pool_shield = concurrent.futures.ProcessPoolExecutor(max_workers=1)
pool_hunter = concurrent.futures.ProcessPoolExecutor(max_workers=13)
pool_segugio = concurrent.futures.ProcessPoolExecutor(max_workers=10)

# --- CALENDARIO LOCALE ---
def is_market_open_locally(epic: str) -> bool:
    """Controlla se il mercato è aperto in base agli orari standard (UTC) per risparmiare chiamate API."""
    try:
        now = datetime.now(pytz.utc)
        day = now.weekday() # 0 = Monday, 6 = Sunday
        hour = now.hour
        minute = now.minute
        time_float = hour + minute / 60.0

        # Crypto (Sempre aperte)
        crypto = ["BTC-USD", "ETH-USD", "XRP-USD", "LTC-USD", "DOGE-USD", "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD"]
        if epic in crypto:
            return True
            
        # Se è weekend, tutto il resto è chiuso
        if day >= 5:
            return False
            
        # US Stocks: 14:30 - 21:00 UTC (09:30 - 16:00 EST)
        us_stocks = ["AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "NVDA", "META", "US30", "US100", "US500"]
        if epic in us_stocks:
            return 14.5 <= time_float < 21.0
            
        # EU/UK Stocks: 07:00 - 15:30 UTC (08:00 - 16:30 GMT)
        eu_stocks = ["GER40", "UK100", "IT40"]
        if epic in eu_stocks:
            return 7.0 <= time_float < 15.5
            
        # Forex e Commodities: Aperte 24h dal Lunedì al Venerdì
        return True
    except Exception as e:
        logger.error(f"Errore nel calcolo orari: {e}")
        return True # Fallback

api = CapitalComAPI()
data_rotator = MultiProviderAPI(api)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="XGBoost Math Microservice (Event-Driven)")

redis_client = None
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

class PriceData(BaseModel):
    prices: List[Dict[str, Any]]
    epic: str

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['SMA_10'] = df['Close'].rolling(window=10).mean()
    df['SMA_50'] = df['Close'].rolling(window=50).mean()
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['Returns'] = df['Close'].pct_change()
    df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
    try:
        df = df.ffill().bfill()
    except AttributeError:
        df = df.fillna(method='ffill').fillna(method='bfill')
    return df.dropna()

GLOBAL_XGBOOST_LAMBDA = 20.0

def run_xgboost_on_prices(prices_data: list) -> float:
    try:
        rows = []
        for p in prices_data:
            rows.append({
                'Open': float(p.get('openPrice', {}).get('bid', 0)),
                'High': float(p.get('highPrice', {}).get('bid', 0)),
                'Low': float(p.get('lowPrice', {}).get('bid', 0)),
                'Close': float(p.get('closePrice', {}).get('bid', 0)),
                'Volume': float(p.get('lastTradedVolume', 0))
            })
        df = pd.DataFrame(rows)
        has_volume = df['Volume'].sum() > 0
        df = add_technical_indicators(df)
        if len(df) < 50: return 0.5
        features = ['Open', 'High', 'Low', 'Close', 'SMA_10', 'SMA_50', 'MACD', 'Signal_Line', 'RSI', 'Returns']
        if has_volume: features.append('Volume')
        X = df[features][:-1]
        y = df['Target'][:-1]
        X_today = df[features].iloc[-1:]
        
        # Filtro di Volatilità (Trend Filter)
        current_rsi = df['RSI'].iloc[-1]
        if 45 <= current_rsi <= 55:
            # Mercato in fase laterale piatta (Volume/Spinta assente). Scarta a prescindere.
            return 0.5
            
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        model = xgb.XGBClassifier(
            n_estimators=100, 
            max_depth=3, 
            learning_rate=0.05, 
            reg_lambda=GLOBAL_XGBOOST_LAMBDA, 
            min_child_weight=5, 
            objective='binary:logistic', 
            random_state=42
        )
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_today)[0][1]
        return float(prob)
    except Exception as e:
        logger.error(f"Errore XGBoost: {e}")
        return 0.5

async def redis_listener():
    logger.info("Avviato Math Engine Redis Listener (Event-Driven)...")
    global redis_client
    while True:
        try:
            redis_client = aioredis.from_url(redis_url)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("news_alerts")
            
            logger.info("In ascolto sul canale 'news_alerts'...")
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    logger.info(f"Ricevuta Notizia Bomba dal NLP: {data['title']} ({data['label']})")
                    
                    # Il Ticker ora viene estratto magicamente dal Segugio NLP (che usa la NER sull'intero web)
                    ticker = data.get('epic')
                    if not ticker:
                        logger.warning(f"Il Segugio ha trovato la notizia '{data['title']}' ma non ha individuato nessun Ticker. Ignoro.")
                        continue
                        
                    logger.info(f"Verifica Tecnica su {ticker} in corso...")
                                   
                    is_open = is_market_open_locally(ticker)
                    
                    if not is_open:
                        logger.info(f"🌙 Mercato CHIUSO per {ticker}. Parcheggio/Aggiorno l'alert NLP sulla Lavagna (Hash Map).")
                        raw_payload = {
                            "epic": ticker,
                            "title": data['title'],
                            "label": data['label'],
                            "score": data['score'],
                            "timestamp": time.time()
                        }
                        await redis_client.hset("waiting_room_alerts", ticker, json.dumps(raw_payload))
                        continue
                        
                    try:
                        # I/O Bound - Usa direttamente il Rotator al posto di Capital.com
                        prices = await asyncio.to_thread(data_rotator.get_historical_prices, ticker, 1000)
                        if len(prices) >= 50:
                            # CPU Bound (Uso pool_segugio a 10 core)
                            loop = asyncio.get_event_loop()
                            prob = await loop.run_in_executor(pool_segugio, run_xgboost_on_prices, prices)
                        else:
                            prob = 0.5
                            
                        # Logica di verifica incrociata
                        is_confirmed = False
                        action_suggested = "HOLD"
                        
                        if data['label'] == 'POSITIVE' and prob > 0.7: 
                            is_confirmed = True
                            action_suggested = "BUY"
                        if data['label'] == 'NEGATIVE' and prob < 0.3: 
                            is_confirmed = True
                            action_suggested = "SELL"
                            
                        if prob >= 0.75:
                            is_confirmed = True
                            action_suggested = "BUY"
                        if prob <= 0.25:
                            is_confirmed = True
                            action_suggested = "SELL"
                            
                        if is_confirmed:
                            payload_for_gemini = {
                                "epic": ticker,
                                "news_title": f"Segugio: {data['title']} (Sentiment: {data['label']})",
                                "news_sentiment": data['label'],
                                "news_score": data['score'],
                                "xgboost_prob": prob,
                                "action_suggested": action_suggested
                            }
                            logger.info(f"✅ Mercato APERTO per {ticker}. Invio diretto a Gemini per esecuzione gap: {payload_for_gemini}")
                            await redis_client.publish("portfolio_alerts", json.dumps(payload_for_gemini))
                            
                    except Exception as e:
                        logger.error(f"Errore NLP Verification su XGBoost: {e}")

        except Exception as e:
            logger.error(f"Errore Listener Redis Math: {e}. Riconnessione tra 5s...")
            await asyncio.sleep(5)

async def portfolio_shield_loop():
    logger.info("Avviato Scudo Portafoglio (Real-Time su posizioni aperte)...")
    global redis_client
    while True:
        try:
            if not redis_client or not api.is_authenticated:
                await asyncio.sleep(10)
                continue
                
            # I/O Bound
            raw_positions = await asyncio.to_thread(api.get_all_positions)
            active_epics = set()
            for p in raw_positions:
                market = p.get('market', {})
                epic = market.get('epic')
                if epic: active_epics.add(epic)
            
            for epic in active_epics:
                try:
                    # I/O Bound - Usa Rotator
                    prices = await asyncio.to_thread(data_rotator.get_historical_prices, epic, 100)
                    if len(prices) < 50:
                        continue
                        
                    # CPU Bound (Uso pool_shield a 1 core fisso)
                    loop = asyncio.get_event_loop()
                    prob = await loop.run_in_executor(pool_shield, run_xgboost_on_prices, prices)
                    
                    if prob <= 0.35:
                        action = "SELL"
                        alert = {
                            "epic": epic,
                            "news_title": "Allarme Scudo: Crollo Tecnico Imminente!",
                            "news_sentiment": "NEGATIVE",
                            "news_score": 1.0,
                            "xgboost_prob": prob,
                            "action_suggested": action
                        }
                        logger.warning(f"🛡️ SCUDO ATTIVO! Crollo rilevato su {epic}: Prob Rialzo {prob*100:.2f}%. Invio SELL_WARNING (Short/Chiusura).")
                        await redis_client.publish("portfolio_alerts", json.dumps(alert))
                    elif prob >= 0.65:
                        action = "BUY"
                        alert = {
                            "epic": epic,
                            "news_title": "Allarme Scudo: Spike Tecnico Imminente!",
                            "news_sentiment": "POSITIVE",
                            "news_score": 1.0,
                            "xgboost_prob": prob,
                            "action_suggested": action
                        }
                        logger.info(f"🛡️ SCUDO ATTIVO! Rally rilevato su {epic}: Prob Rialzo {prob*100:.2f}%. Invio BUY_WARNING.")
                        await redis_client.publish("portfolio_alerts", json.dumps(alert))
                        
                except Exception as e:
                    logger.warning(f"Errore Scudo su {epic}: {e}")
                    
            await asyncio.sleep(45) # Controllo ogni 45 secondi
            
        except Exception as e:
            logger.error(f"Errore Loop Scudo: {e}")
            await asyncio.sleep(10)


async def analyze_epic_async(epic: str):
    """Funzione atomica per scaricare i dati e delegare l'elaborazione XGBoost ai 24 core"""
    try:
        if not is_market_open_locally(epic):
            return None
            
        # I/O Bound: Scaricamento rete via Rotator
        prices = await asyncio.to_thread(data_rotator.get_historical_prices, epic, 1000)
        if not prices or len(prices) < 50:
            return None
            
        # CPU Bound: Delegato al ProcessPool a 13 Core del Cacciatore
        loop = asyncio.get_event_loop()
        prob = await loop.run_in_executor(pool_hunter, run_xgboost_on_prices, prices)
        
        return {"epic": epic, "prob": prob}
    except Exception as e:
        return None

async def market_hunter_loop():
    logger.info("Avviato Cacciatore Multicore (24 vCPU - Smart Batching)...")
    global redis_client
    
    # Caricamento del parco asset globale (S&P 500, Crypto, Forex, ecc.)
    try:
        with open('global_assets.json', 'r') as f:
            mega_list = json.load(f)
        logger.info(f"Cacciatore armato con {len(mega_list)} asset mondiali.")
    except Exception:
        logger.warning("global_assets.json non trovato, uso lista di fallback.")
        mega_list = [
            "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "NVDA", "META", 
            "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD"
        ]
    
    while True:
        try:
            if not redis_client or not api.is_authenticated:
                await asyncio.sleep(10)
                continue
                
            # --- SMART BATCHING ---
            # Suddividiamo i 1000 asset in blocchi da 12 per evitare il Ban
            chunk_size = 12
            for i in range(0, len(mega_list), chunk_size):
                chunk = mega_list[i:i+chunk_size]
                
                # Creiamo 12 task paralleli che sfrutteranno l'I/O asincrono e i 24 core per l'XGBoost
                tasks = [analyze_epic_async(epic) for epic in chunk]
                results = await asyncio.gather(*tasks)
                
                for res in results:
                    if not res:
                        continue
                        
                    prob = res['prob']
                    epic = res['epic']
                    
                    if prob >= 0.65:
                        alert = {
                            "epic": epic,
                            "news_title": "Cacciatore: Occasione Tecnica Pura (LONG)",
                            "news_sentiment": "POSITIVE",
                            "news_score": 1.0,
                            "xgboost_prob": prob,
                            "action_suggested": "BUY"
                        }
                        logger.info(f"🏹 CACCIATORE: Trova LONG su {epic} (Prob {prob*100:.2f}%). Invio.")
                        await redis_client.publish("portfolio_alerts", json.dumps(alert))
                        
                    elif prob <= 0.35:
                        alert = {
                            "epic": epic,
                            "news_title": "Cacciatore: Occasione Tecnica Pura (SHORT)",
                            "news_sentiment": "NEGATIVE",
                            "news_score": 1.0,
                            "xgboost_prob": prob,
                            "action_suggested": "SELL"
                        }
                        logger.info(f"🏹 CACCIATORE: Trova SHORT su {epic} (Prob {prob*100:.2f}%). Invio.")
                        await redis_client.publish("portfolio_alerts", json.dumps(alert))
                
                # Pausa Anti-Ban per respirare tra un blocco e l'altro
                await asyncio.sleep(3)
                
            # Pausa ridotta a 30 secondi grazie al Data Rotator multi-provider!
            await asyncio.sleep(30)
            
        except Exception as e:
            logger.error(f"Errore Cacciatore: {e}")
            await asyncio.sleep(60)

async def waiting_room_loop():
    logger.info("Avviata Lavagna d'Attesa (Pre-Market Sniper, Hash Map)...")
    global redis_client
    while True:
        try:
            if not redis_client:
                await asyncio.sleep(10)
                continue
                
            try:
                length = await redis_client.hlen("waiting_room_alerts")
            except Exception as e:
                if "WRONGTYPE" in str(e):
                    logger.warning("Rilevato WRONGTYPE su waiting_room_alerts. Resetto la chiave.")
                    await redis_client.delete("waiting_room_alerts")
                else:
                    logger.error(f"Errore accesso Redis Lavagna: {e}")
                await asyncio.sleep(5)
                continue
                
            if length > 0:
                alerts_dict = await redis_client.hgetall("waiting_room_alerts")
                
                current_time = time.time()
                
                for ticker_bytes, alert_bytes in alerts_dict.items():
                    ticker = ticker_bytes.decode('utf-8') if isinstance(ticker_bytes, bytes) else ticker_bytes
                    alert_data = json.loads(alert_bytes)
                    ts = alert_data.get('timestamp', current_time)
                    
                    if current_time - ts > (72 * 3600):
                        logger.info(f"Notizia in attesa su {ticker} scaduta (>72h). Scartata.")
                        await redis_client.hdel("waiting_room_alerts", ticker)
                        continue
                        
                    if is_market_open_locally(ticker):
                        logger.info(f"🔔 MERCATO APERTO per {ticker}! Ri-valutazione XGBoost della Notizia dalla Lavagna in corso...")
                        
                        # Rimuoviamo subito l'alert dalla lavagna per evitare doppie esecuzioni
                        await redis_client.hdel("waiting_room_alerts", ticker)
                        
                        # Recupero dati
                        news_title = alert_data.get('title', alert_data.get('news_title', 'Notizia Sconosciuta'))
                        news_label = alert_data.get('label', alert_data.get('news_sentiment', 'NEUTRAL'))
                        news_score = alert_data.get('score', alert_data.get('news_score', 0.5))
                        
                        try:
                            # I/O Bound - Usa Capital.com
                            prices = await asyncio.to_thread(api.get_historical_prices, ticker, 100)
                            if len(prices) >= 50:
                                # CPU Bound (Uso pool_segugio a 10 core)
                                loop = asyncio.get_event_loop()
                                prob = await loop.run_in_executor(pool_segugio, run_xgboost_on_prices, prices)
                            else:
                                prob = 0.5
                                
                            action_suggested = "HOLD"
                            is_confirmed = False
                            
                            if news_label == 'POSITIVE' and prob > 0.6: 
                                is_confirmed = True
                                action_suggested = "BUY"
                            if news_label == 'NEGATIVE' and prob < 0.4: 
                                is_confirmed = True
                                action_suggested = "SELL"
                                
                            if prob >= 0.65:
                                is_confirmed = True
                                action_suggested = "BUY"
                            if prob <= 0.35:
                                is_confirmed = True
                                action_suggested = "SELL"
                                
                            if is_confirmed:
                                final_payload = {
                                    "epic": ticker,
                                    "news_title": f"Segugio: {news_title} (Sentiment: {news_label})",
                                    "news_sentiment": news_label,
                                    "news_score": news_score,
                                    "xgboost_prob": prob,
                                    "action_suggested": action_suggested
                                }
                                logger.info(f"🚀 RI-VALUTAZIONE SUPERATA! Invio a Gemini per esecuzione gap: {final_payload}")
                                await redis_client.publish("portfolio_alerts", json.dumps(final_payload))
                            else:
                                logger.warning(f"❌ Ri-valutazione fallita per {ticker}. La notizia non è più supportata dai prezzi attuali. Scartata.")
                                
                        except Exception as e:
                            logger.error(f"Errore ricalcolo Waiting Room per {ticker}: {e}")
                            
        except Exception as e:
            logger.error(f"Errore Waiting Room Loop: {e}")
            
        await asyncio.sleep(60)

async def lambda_updater_loop():
    global GLOBAL_XGBOOST_LAMBDA
    while True:
        try:
            if redis_client:
                val = await redis_client.get("config:xgboost_lambda")
                if val:
                    GLOBAL_XGBOOST_LAMBDA = float(val)
        except Exception as e:
            logger.error(f"Errore lettura lambda: {e}")
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    logger.info("Connessione a Capital.com in corso per il Math Engine...")
    success = api.authenticate()
    if success:
        logger.info("🚀 API Capital.com Connessa per il Math Engine!")
        
    global redis_client
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = aioredis.from_url(redis_url)
        logger.info("Connesso a Redis con successo!")
    except Exception as e:
        logger.error(f"Errore di connessione a Redis: {e}")
        
    logger.info("Avvio thread del Math Engine...")
    asyncio.create_task(redis_listener())
    asyncio.create_task(market_hunter_loop())
    asyncio.create_task(portfolio_shield_loop())
    asyncio.create_task(waiting_room_loop())
    asyncio.create_task(lambda_updater_loop())

@app.post("/predict")
def calculate_probability(request: PriceData):
    try:
        if len(request.prices) < 50:
            return {"probability": 0.5, "status": "insufficient_data"}
        prob = run_xgboost_on_prices(request.prices)
        return {"probability": float(prob), "status": "success"}
    except Exception as e:
        logger.error(f"XGBoost Fallito per {request.epic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
