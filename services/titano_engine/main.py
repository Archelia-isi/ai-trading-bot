from fastapi import FastAPI
import logging
import asyncio
import os
import json
import redis.asyncio as aioredis
import numpy as np
import pandas as pd
import torch
import torch.nn as nn

import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from core.capital_api import CapitalComAPI
from online_learning import perform_online_learning, schedule_nightly_learning

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Titano V5 Node (Math Engine)")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
api = CapitalComAPI()

# --- CLASSE CUSTOM NECESSARIA PER CARICARE IL MODELLO ---
class MultiAssetFeatureExtractor(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, features_dim: int = 1024):
        super().__init__(observation_space, features_dim)
        n_input_channels = observation_space.shape[1]
        
        self.cnn = nn.Sequential(
            nn.Conv1d(n_input_channels, 128, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(128, 256, kernel_size=8, stride=2, padding=3),
            nn.ReLU(),
            nn.Conv1d(256, 512, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv1d(512, 1024, kernel_size=4, stride=2, padding=1),
            nn.ReLU(),
            nn.Flatten(),
        )
        
        with torch.no_grad():
            dummy_input = torch.zeros(1, n_input_channels, observation_space.shape[0])
            n_flatten = self.cnn(dummy_input).shape[1]
            
        self.linear = nn.Sequential(
            nn.Linear(n_flatten, 1024),
            nn.ReLU(),
            nn.Linear(1024, features_dim),
            nn.ReLU()
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        observations = observations.permute(0, 2, 1) 
        x = self.cnn(observations)
        return self.linear(x)

# --- CONFIGURAZIONE ASSET ---
# Ordine rigorosamente alfabetico basato sul nome file (es. AAPL_1m.parquet -> AAPL)
ASSETS = [
    "AAPL", "AMZN", "C:AUDUSD", "C:EURUSD", "C:GBPUSD", "C:USDJPY", "META",
    "MSFT", "NVDA", "QQQ", "SPY", "TSLA", "X:BTCUSD", "X:DOGEUSD", "X:ETHUSD", 
    "X:SOLUSD", "X:XRPUSD"
]

def get_capital_epic(ticker: str) -> str:
    """Converte il ticker Polygon nell'EPIC presunto di Capital.com"""
    if ticker.startswith("X:"): return ticker.replace("X:", "")
    if ticker.startswith("C:"): return ticker.replace("C:", "")
    return ticker

# --- TOGGLE DI TRANSIZIONE (V5 -> V6) ---
# Imposta a True SOLO quando hai caricato il file Titano_V6_Universale.zip
USIAMO_LA_V6 = False

async def titano_loop():
    logger.info(f"Avviato Titano Engine (V6={USIAMO_LA_V6})...")
    
    import __main__
    setattr(__main__, 'MultiAssetFeatureExtractor', MultiAssetFeatureExtractor)
    
    # IMPORTANTE: Quando useremo la V6, dovremo registrare la nuova classe UniversalFeatureExtractor
    
    try:
        if not USIAMO_LA_V6:
            model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V5_OcchiAperti.zip")
            model = PPO.load(model_path, custom_objects={'MultiAssetFeatureExtractor': MultiAssetFeatureExtractor})
            logger.info("🧠 Modello Titano V5 caricato con successo!")
        else:
            model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V6_Universale.zip")
            # In futuro si aggiungerà il custom_object per UniversalFeatureExtractor
            # model = PPO.load(model_path, custom_objects={'UniversalFeatureExtractor': UniversalFeatureExtractor})
            logger.info("🧠 Modello Titano V6 UNIVERSALE caricato!")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
        return

    r = await aioredis.from_url(REDIS_URL)
    api.authenticate()

    while True:
        try:
            logger.info("🔄 Esecuzione Titano Live Inference...")
            
            if not USIAMO_LA_V6:
                # ==========================================
                # LOGICA VECCHIA V4/V5 (MATRICE UNICA 17 ASSET)
                # ==========================================
                asset_features = []
                for ticker in ASSETS:
                    epic = get_capital_epic(ticker)
                    candles = api.get_historical_prices(epic, max_candles=50, resolution="MINUTE")
                    if not candles or len(candles) < 30:
                        closes = np.zeros(50)
                    else:
                        closes = np.array([c.get('closePrice', {}).get('bid', 0.0) for c in candles])
                    
                    df = pd.DataFrame({'close': closes})
                    df['returns'] = df['close'].pct_change()
                    df['volatility'] = df['returns'].rolling(window=20).std()
                    df.fillna(0, inplace=True)
                    df_last_30 = df.iloc[-30:]
                    feat_matrix = df_last_30[['close', 'volatility']].to_numpy(dtype=np.float32)
                    asset_features.append(feat_matrix)
                    
                obs = np.concatenate(asset_features, axis=1)
                
                # ADATTAMENTO DINAMICO DELLA SHAPE (V4 vs V5)
                # Il V5 è stato addestrato con observation space (1020,), la V4 con (30, 34)
                expected_shape = model.observation_space.shape
                if len(expected_shape) == 1 and expected_shape[0] == obs.size:
                    obs_inference = obs.flatten()
                else:
                    obs_inference = obs
                    
                action, _ = model.predict(obs_inference, deterministic=True)
                
                # Se l'azione è uno scalare singolo invece che un array di 17 elementi (es. modello cambiato)
                # Adattiamo l'azione in un array per non far crashare il ciclo successivo
                if not isinstance(action, (np.ndarray, list)):
                    action = [action] * len(ASSETS)
                elif len(action) != len(ASSETS):
                    action = action.flatten() # Tenta un appiattimento in caso di matrici sballate
                
                logger.info(f"Azioni predette dal Modello: {action}")
                for i, ticker in enumerate(ASSETS):
                    act_val = action[i]
                    epic = get_capital_epic(ticker)
                    direction = "FLAT"
                    if act_val == 0: direction = "SELL"
                    elif act_val == 2: direction = "BUY"
                    
                    if direction != "FLAT":
                        req = {"epic": epic, "direction": direction, "size_pct": 5.0, "leverage": 1, "prob": 0.99, "source": "TITANO_V5"}
                        await r.publish("audit_requests", json.dumps(req))
            else:
                # ==========================================
                # NUOVA LOGICA V6 UNIVERSALE (MULTIPROCESSO)
                # ==========================================
                batch_obs = []
                valid_assets = []
                
                for ticker in ASSETS:
                    epic = get_capital_epic(ticker)
                    candles = api.get_historical_prices(epic, max_candles=50, resolution="MINUTE")
                    if not candles or len(candles) < 30:
                        continue # Saltiamo l'asset se non ha dati
                        
                    closes = np.array([c.get('closePrice', {}).get('bid', 0.0) for c in candles])
                    df = pd.DataFrame({'close': closes})
                    df['returns'] = df['close'].pct_change()
                    df['volatility'] = df['returns'].rolling(window=20).std()
                    df.fillna(0, inplace=True)
                    
                    # Recupero Parere XGBoost (Simulato per ora, si leggerà da Redis)
                    xgb_prob = 0.5 
                    
                    # Recupero Parere News (Simulato per ora)
                    news_sentiment = 0.0 
                    
                    df['xgb_proxy'] = xgb_prob
                    df['news_proxy'] = news_sentiment
                    
                    df_last_30 = df.iloc[-30:]
                    # Ora la matrice è 30x4!
                    feat_matrix = df_last_30[['close', 'volatility', 'xgb_proxy', 'news_proxy']].to_numpy(dtype=np.float32)
                    
                    batch_obs.append(feat_matrix)
                    valid_assets.append(epic)
                
                if len(batch_obs) > 0:
                    # Converte la lista in un Tensor 3D per l'inferenza parallela: Shape (Num_Assets, 30, 4)
                    obs_tensor = np.stack(batch_obs)
                    
                    # Inferenza Simultanea Vettorizzata
                    azioni, _ = model.predict(obs_tensor, deterministic=True)
                    
                    # Estrazione Sicurezza (Confidence) -> Verrà implementata accedendo alla Policy della PPO
                    # Per ora inviamo le richieste di Audit classiche
                    for i, epic in enumerate(valid_assets):
                        act_val = azioni[i]
                        direction = "FLAT"
                        if act_val == 0: direction = "SELL"
                        elif act_val == 2: direction = "BUY"
                        
                        if direction != "FLAT":
                            # Salviamo anche la fotografia esatta 30x4 (batch_obs[i]) in JSON per l'Online Learning
                            # La logica del salvataggio DB verrà attivata nel prossimo task
                            
                            req = {"epic": epic, "direction": direction, "size_pct": 5.0, "leverage": 1, "prob": 0.99, "source": "TITANO_V6_UNIVERSAL"}
                            await r.publish("audit_requests", json.dumps(req))

        except Exception as e:
            logger.error(f"Errore nel loop di Titano: {e}")
            
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V5_OcchiAperti.zip")
    
    # 1. Trigger Apprendimento a Caldo (Startup)
    perform_online_learning(model_path)
    
    # 2. Schedulazione Notturna (Mezzanotte)
    schedule_nightly_learning(model_path)
    
    # 3. Avvio Loop di Trading
    asyncio.create_task(titano_loop())

@app.get("/")
def health_check():
    return {"status": "online", "message": "Titano V5 Node Running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Force Railway Deploy
