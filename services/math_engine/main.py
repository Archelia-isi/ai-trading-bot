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
                    # Ticker extraction ultra-basica
                    ticker = "AAPL" 
                    if "bitcoin" in data['title'].lower() or "btc" in data['title'].lower(): ticker = "BTC-USD"
                    elif "tesla" in data['title'].lower() or "musk" in data['title'].lower(): ticker = "TSLA"
                    
                    logger.info(f"Verifica Tecnica su {ticker} in corso...")
                    
                    try:
                        # Usiamo la libreria locale di XGBoost
                        df_yf = yf.download(ticker, period="1y", interval="1d", progress=False)
                        prices = []
                        for date, row in df_yf.iterrows():
                            # Se MultiIndex (yf recente) prendi il valore
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
                        
                        logger.info(f"Conferma Tecnica XGBoost su {ticker}: {prob*100:.2f}% Prob. Rialzo")
                        
                        # Se NLP dice POSITIVE e Math dice >0.6 (o viceversa) -> Allarme confermato!
                        is_confirmed = False
                        if data['label'] == 'POSITIVE' and prob > 0.6: is_confirmed = True
                        if data['label'] == 'NEGATIVE' and prob < 0.4: is_confirmed = True
                        
                        if is_confirmed or prob > 0.85 or prob < 0.15:
                            alert_payload = {
                                "epic": ticker,
                                "news_title": data['title'],
                                "news_sentiment": data['label'],
                                "news_score": data['score'],
                                "xgboost_prob": prob,
                                "action_suggested": "BUY" if prob > 0.5 else "SELL"
                            }
                            logger.info(f"🔥 SEGNALE CONFERMATO! Invio al Portfolio Manager: {alert_payload}")
                            await redis_client.publish("portfolio_alerts", json.dumps(alert_payload))
                            
                    except Exception as e:
                        logger.error(f"Errore analisi yfinance: {e}")

        except Exception as e:
            logger.error(f"Errore Listener Redis Math: {e}. Riconnessione tra 5s...")
            await asyncio.sleep(5)

async def market_scanner_loop():
    logger.info("Avviato Math Engine Market Scanner (Loop Continuo)...")
    global redis_client
    # Lista di asset monitorati costantemente (Top Mercato + Portafoglio)
    # In futuro questa lista può essere aggiornata dinamicamente dal DB
    monitored_assets = ["AAPL", "MSFT", "TSLA", "BTC-USD", "ETH-USD", "GC=F"]
    
    while True:
        try:
            if not redis_client:
                await asyncio.sleep(5)
                continue
                
            import yfinance as yf
            for ticker in monitored_assets:
                try:
                    df_yf = yf.download(ticker, period="1y", interval="1d", progress=False)
                    if len(df_yf) < 50: continue
                    
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
                    
                    # Se trova un'occasione pura (senza news) o un pericolo per il portafoglio
                    if prob > 0.85 or prob < 0.15:
                        action = "BUY_OPPORTUNITY" if prob > 0.85 else "SELL_WARNING"
                        alert_payload = {
                            "epic": ticker,
                            "news_title": "Nessuna News (Analisi Tecnica Pura)",
                            "news_sentiment": "NEUTRAL",
                            "news_score": 0.5,
                            "xgboost_prob": prob,
                            "action_suggested": action
                        }
                        logger.info(f"📊 ALERT TECNICO {action} su {ticker}: Prob {prob*100:.2f}%. Invio al Portfolio Manager.")
                        await redis_client.publish("portfolio_alerts", json.dumps(alert_payload))
                        
                except Exception as e:
                    logger.warning(f"Errore scansione tecnica su {ticker}: {e}")
            
            # Scansiona tutto il mercato ogni ora (per non farci bannare dalle API)
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"Errore Market Scanner Loop: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(redis_listener())
    asyncio.create_task(market_scanner_loop())

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
