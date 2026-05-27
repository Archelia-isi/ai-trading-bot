from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="XGBoost Math Microservice")

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
    
    # Compatibilità Pandas
    try:
        df = df.ffill().bfill()
    except AttributeError:
        df = df.fillna(method='ffill').fillna(method='bfill')
        
    return df.dropna()

@app.post("/predict")
def calculate_probability(request: PriceData):
    try:
        prices_data = request.prices
        epic = request.epic
        
        if len(prices_data) < 50:
            logger.warning(f"XGBoost: Dati storici insufficienti ({len(prices_data)} giorni) per {epic}.")
            return {"probability": 0.5, "status": "insufficient_data"}
            
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
        
        if len(df) < 50:
             logger.warning(f"XGBoost: Pochi dati post-pulizia per {epic}.")
             return {"probability": 0.5, "status": "post_clean_insufficient"}
        
        features = ['Open', 'High', 'Low', 'Close', 'SMA_10', 'SMA_50', 'MACD', 'Signal_Line', 'RSI', 'Returns']
        if has_volume:
            features.append('Volume')
            
        X = df[features][:-1]
        y = df['Target'][:-1]
        X_today = df[features].iloc[-1:]
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        model = xgb.XGBClassifier(
            n_estimators=100, 
            max_depth=3, 
            learning_rate=0.1, 
            objective='binary:logistic', 
            random_state=42
        )
        
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_today)[0][1]
        
        return {"probability": float(prob), "status": "success"}
        
    except Exception as e:
        logger.error(f"XGBoost Fallito per {request.epic}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
