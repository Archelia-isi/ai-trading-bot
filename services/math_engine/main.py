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
import requests
import numpy as np
import yfinance as yf
from capital_api import CapitalComAPI
from datetime import datetime
import pytz
import time

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
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        model = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, objective='binary:logistic', random_state=42)
        model.fit(X_train, y_train)
        return float(model.predict_proba(X_today)[0][1])
    except Exception as e:
        logger.error(f"Errore train XGBoost locale: {e}")
        return 0.5

async def redis_listener():
    logger.info("Avviato Math Engine Redis Listener (Event-Driven)...")
    global redis_client
    while True:
        try:
            redis_client = await aioredis.from_url(redis_url)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("news_alerts")
            
            logger.info("In ascolto sul canale 'news_alerts'...")
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    logger.info(f"Ricevuta Notizia Bomba dal NLP: {data['title']} ({data['label']})")
                    
                    # 1. Recupero dati per l'asset incriminato (Mock: Usiamo Yahoo Finance API libera per semplicità nel microservizio isolato)
                    # In un sistema reale passiamo l'epic o scarichiamo da polygon/yahoo
                    import yfinance as yf
                    ticker = "AAPL" 
                    if "bitcoin" in data['title'].lower() or "btc" in data['title'].lower(): ticker = "BTC-USD"
                    elif "tesla" in data['title'].lower() or "musk" in data['title'].lower(): ticker = "TSLA"
                    
                    logger.info(f"Verifica Tecnica su {ticker} in corso...")
                                   
                    is_open = is_market_open_locally(ticker)
                    
                    try:
                        df_yf = yf.download(ticker, period="1y", interval="1d", progress=False)
                        if len(df_yf) >= 50:
                            prices = []
                            for date, row in df_yf.iterrows():
                                open_p = row['Open'].iloc[0] if isinstance(row['Open'], pd.Series) else row['Open']
                                high_p = row['High'].iloc[0] if isinstance(row['High'], pd.Series) else row['High']
                                low_p = row['Low'].iloc[0] if isinstance(row['Low'], pd.Series) else row['Low']
                                close_p = row['Close'].iloc[0] if isinstance(row['Close'], pd.Series) else row['Close']
                                vol_p = row['Volume'].iloc[0] if isinstance(row['Volume'], pd.Series) else row['Volume']
                                prices.append({
                                    'openPrice': {'bid': float(open_p)},
                                    'highPrice': {'bid': float(high_p)},
                                    'lowPrice': {'bid': float(low_p)},
                                    'closePrice': {'bid': float(close_p)},
                                    'lastTradedVolume': float(vol_p)
                                })
                            prob = run_xgboost_on_prices(prices)
                        else:
                            prob = 0.5
                            
                        action_suggested = "BUY" if prob > 0.65 else ("SELL" if prob < 0.35 else "HOLD")
                        
                        payload_for_gemini = {
                            "epic": ticker,
                            "news_title": f"Segugio: {data['title']} (Sentiment: {data['label']})",
                            "news_sentiment": data['label'],
                            "news_score": data['score'],
                            "xgboost_prob": prob,
                            "action_suggested": action_suggested
                        }
                        
                        if is_open:
                            logger.info(f"✅ Mercato APERTO per {ticker}. Invio diretto a Gemini per esecuzione.")
                            await redis_client.publish("portfolio_alerts", json.dumps(payload_for_gemini))
                        else:
                            logger.info(f"🌙 Mercato CHIUSO per {ticker}. Parcheggio l'alert nella Stanza d'Attesa.")
                            payload_for_gemini['timestamp'] = time.time()
                            await redis_client.rpush("waiting_room_alerts", json.dumps(payload_for_gemini))
                            
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
                
            raw_positions = api.get_all_positions()
            active_epics = set()
            for p in raw_positions:
                market = p.get('market', {})
                epic = market.get('epic')
                if epic: active_epics.add(epic)
            
            for epic in active_epics:
                try:
                    prices = api.get_historical_prices(epic, hours=100)
                    if len(prices) < 50:
                        continue
                        
                    prob = run_xgboost_on_prices(prices)
                    
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


async def market_hunter_loop():
    logger.info("Avviato Cacciatore di Occasioni (Mega-Lista multi-direzionale)...")
    global redis_client
    
    mega_list = [
        "AAPL", "MSFT", "TSLA", "AMZN", "GOOGL", "NVDA", "META", 
        "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD",
        "GOLD", "SILVER", "OIL_BRENT", "NATURALGAS",
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
        "US30", "US100", "US500", "GER40", "UK100"
    ]
    
    while True:
        try:
            if not redis_client or not api.is_authenticated:
                await asyncio.sleep(10)
                continue
                
            for epic in mega_list:
                try:
                    if not is_market_open_locally(epic):
                        logger.info(f"Mercato chiuso per {epic}. Analisi saltata. Il cacciatore si sposta sul prossimo.")
                        await asyncio.sleep(0.5)
                        continue
                        
                    prices = api.get_historical_prices(epic, hours=100)
                    prob = run_xgboost_on_prices(prices)
                    
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
                        
                except Exception as e:
                    pass
                
                await asyncio.sleep(10)
                
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Errore Cacciatore: {e}")
            await asyncio.sleep(60)

async def waiting_room_loop():
    logger.info("Avviata Stanza d'Attesa (Pre-Market Sniper)...")
    global redis_client
    while True:
        try:
            if not redis_client:
                await asyncio.sleep(10)
                continue
                
            length = await redis_client.llen("waiting_room_alerts")
            if length > 0:
                alerts = await redis_client.lrange("waiting_room_alerts", 0, -1)
                await redis_client.delete("waiting_room_alerts")
                
                current_time = time.time()
                
                for alert_bytes in alerts:
                    alert_data = json.loads(alert_bytes)
                    ts = alert_data.get('timestamp', current_time)
                    
                    if current_time - ts > (72 * 3600):
                        logger.info(f"Notizia in attesa su {alert_data['epic']} scaduta (>72h). Scartata.")
                        continue
                        
                    ticker = alert_data['epic']
                    
                    if is_market_open_locally(ticker):
                        logger.info(f"🔔 MERCATO APERTO per {ticker}! Sgancio l'alert a Gemini dalla Stanza d'Attesa!")
                        if 'timestamp' in alert_data:
                            del alert_data['timestamp']
                        await redis_client.publish("portfolio_alerts", json.dumps(alert_data))
                    else:
                        await redis_client.rpush("waiting_room_alerts", json.dumps(alert_data))
                        
        except Exception as e:
            logger.error(f"Errore Waiting Room Loop: {e}")
            
        await asyncio.sleep(60)

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
