import logging
import yfinance as yf
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

class XGBoostEngine:
    def __init__(self):
        logger.info("Modulo XGBoost inizializzato.")

    def add_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcola indicatori tecnici di base per alimentare l'IA Matematica."""
        df = df.copy()
        
        # Medie Mobili
        df['SMA_10'] = df['Close'].rolling(window=10).mean()
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # RSI (14 periodi)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # Variazione % Prezzo
        df['Returns'] = df['Close'].pct_change()
        
        # Target: 1 se il prezzo CHIUDE più in alto del prezzo di APERTURA del giorno SUCCESSIVO
        # Spostiamo indietro di 1 giorno per avere il target sulle feature di oggi
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        
        return df.dropna()

    def get_yahoo_ticker(self, asset_name: str) -> str:
        """Cerca il ticker Yahoo Finance corretto a partire dal nome dell'azienda."""
        try:
            import requests
            url = f"https://query2.finance.yahoo.com/v1/finance/search"
            params = {"q": asset_name, "quotesCount": 1, "newsCount": 0}
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            
            # Eccezione per criptovalute più comuni
            if "bitcoin" in asset_name.lower() or "btc" in asset_name.lower(): return "BTC-USD"
            if "ethereum" in asset_name.lower() or "eth" in asset_name.lower(): return "ETH-USD"
            
            res = requests.get(url, params=params, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if "quotes" in data and len(data["quotes"]) > 0:
                    return data["quotes"][0]["symbol"]
        except Exception as e:
            logger.error(f"Errore ricerca ticker Yahoo per {asset_name}: {e}")
        return asset_name

    def calculate_probability(self, asset_name: str) -> float:
        """
        Scarica 1 anno di storico tramite yfinance, addestra XGBoost e restituisce
        la probabilità (0-1) di una candela verde imminente.
        """
        try:
            # Ricerca rapida del ticker Yahoo Finance
            ticker_symbol = self.get_yahoo_ticker(asset_name)
            logger.info(f"XGBoost: Trovato Ticker Yahoo '{ticker_symbol}' per l'asset '{asset_name}'")
            
            ticker_obj = yf.Ticker(ticker_symbol)
            
            # Scarichiamo 1 anno di dati giornalieri
            df = ticker_obj.history(period="1y")
            
            if df.empty or len(df) < 50:
                logger.warning(f"XGBoost: Dati storici insufficienti per {asset_name} su Yahoo Finance.")
                return 0.5 # Neutrale

            df = self.add_technical_indicators(df)
            
            if len(df) < 100:
                 logger.warning(f"XGBoost: Pochi dati validi per l'addestramento su {asset_name}.")
                 return 0.5
            
            # Feature ed Etichette
            features = ['Open', 'High', 'Low', 'Close', 'Volume', 'SMA_10', 'SMA_50', 'MACD', 'Signal_Line', 'RSI', 'Returns']
            X = df[features][:-1] # Escludiamo l'ultimo giorno per l'addestramento (il target non è noto)
            y = df['Target'][:-1]
            
            # Dati di oggi per prevedere domani
            X_today = df[features].iloc[-1:]
            
            # Divisione train/test
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
            
            # Modello XGBoost Classifier
            model = xgb.XGBClassifier(
                n_estimators=100, 
                max_depth=3, 
                learning_rate=0.1, 
                objective='binary:logistic', 
                random_state=42
            )
            
            model.fit(X_train, y_train)
            
            # Calcolo probabilità per oggi
            prob = model.predict_proba(X_today)[0][1] # Probabilità della classe 1 (Rialzo)
            
            return float(prob)
            
        except Exception as e:
            logger.error(f"XGBoost Fallito per {asset_name}: {e}")
            return 0.5
