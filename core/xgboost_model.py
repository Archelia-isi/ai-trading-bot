import logging
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from core.capital_api import CapitalComAPI

logger = logging.getLogger(__name__)

class XGBoostEngine:
    def __init__(self):
        logger.info("Modulo XGBoost inizializzato (Sorgente Dati: Capital.com).")

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
        df['Target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
        
        # Fill NaN iniziale invece di droppare tutto (salviamo i dati dove possibile)
        df = df.fillna(method='bfill')
        return df.dropna()

    def calculate_probability(self, epic: str, capital_api: CapitalComAPI) -> float:
        """
        Scarica 1 anno di storico tramite Capital.com API, addestra XGBoost e restituisce
        la probabilità (0-1) di una candela verde imminente.
        """
        try:
            logger.info(f"XGBoost: Download dati storici (250gg) per EPIC '{epic}' da Capital.com...")
            
            # 1. Recupero Dati da Capital.com (Resolution=DAY, max=250)
            url = f"{capital_api.base_url}/prices/{epic}?resolution=DAY&max=250"
            res = capital_api._requests_get(url)
            
            if not res or res.status_code != 200:
                logger.error(f"XGBoost: Impossibile scaricare storico da Capital.com per {epic}")
                return 0.5
                
            prices_data = res.json().get('prices', [])
            if len(prices_data) < 50:
                logger.warning(f"XGBoost: Dati storici insufficienti ({len(prices_data)} giorni) per {epic}.")
                return 0.5
                
            # 2. Conversione in DataFrame
            rows = []
            for p in prices_data:
                rows.append({
                    'Open': p.get('openPrice', {}).get('bid', 0),
                    'High': p.get('highPrice', {}).get('bid', 0),
                    'Low': p.get('lowPrice', {}).get('bid', 0),
                    'Close': p.get('closePrice', {}).get('bid', 0),
                    'Volume': p.get('lastTradedVolume', 0)
                })
                
            df = pd.DataFrame(rows)
            
            # Se la colonna Volume è tutta a 0 (comune per CFD/Forex su Capital), la togliamo dalle feature
            has_volume = df['Volume'].sum() > 0

            # 3. Indicatori Tecnici
            df = self.add_technical_indicators(df)
            
            if len(df) < 50:
                 logger.warning(f"XGBoost: Pochi dati post-pulizia per {epic}.")
                 return 0.5
            
            # Feature ed Etichette Dinamiche
            features = ['Open', 'High', 'Low', 'Close', 'SMA_10', 'SMA_50', 'MACD', 'Signal_Line', 'RSI', 'Returns']
            if has_volume:
                features.append('Volume')
                
            X = df[features][:-1]
            y = df['Target'][:-1]
            
            X_today = df[features].iloc[-1:]
            
            # 4. Addestramento Modello
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
            
            model = xgb.XGBClassifier(
                n_estimators=100, 
                max_depth=3, 
                learning_rate=0.1, 
                objective='binary:logistic', 
                random_state=42
            )
            
            model.fit(X_train, y_train)
            
            # 5. Previsione
            prob = model.predict_proba(X_today)[0][1]
            
            return float(prob)
            
        except Exception as e:
            logger.error(f"XGBoost Fallito per {epic}: {e}")
            return 0.5
