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

app = FastAPI(title="Titano V4 Node (Math Engine)")
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

async def titano_loop():
    logger.info("Avviato Titano V4 Engine (Loop a 1 minuto)...")
    
    # Registriamo la classe custom nel modulo principale per permettere a PPO di trovarla
    import __main__
    setattr(__main__, 'MultiAssetFeatureExtractor', MultiAssetFeatureExtractor)
    
    try:
        model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V4_OcchiAperti.zip")
        model = PPO.load(model_path, custom_objects={'MultiAssetFeatureExtractor': MultiAssetFeatureExtractor})
        logger.info("🧠 Modello Titano V4 caricato con successo!")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
        return

    r = await aioredis.from_url(REDIS_URL)
    api.authenticate()

    while True:
        try:
            logger.info("🔄 Esecuzione Titano Live Inference...")
            asset_features = []
            
            for ticker in ASSETS:
                epic = get_capital_epic(ticker)
                
                # Preleviamo le ultime 50 candele al minuto per avere margine per il calcolo della volatilità (rolling 20)
                candles = api.get_historical_prices(epic, max_candles=50, resolution="MINUTE")
                
                if not candles or len(candles) < 30:
                    logger.warning(f"Dati insufficienti per {epic}. Uso array di zeri.")
                    closes = np.zeros(50)
                else:
                    closes = np.array([c.get('closePrice', {}).get('bid', 0.0) for c in candles])
                
                df = pd.DataFrame({'close': closes})
                df['returns'] = df['close'].pct_change()
                df['volatility'] = df['returns'].rolling(window=20).std()
                
                df.fillna(0, inplace=True)
                
                # Prendiamo esattamente le ultime 30 candele
                df_last_30 = df.iloc[-30:]
                
                # Estraiamo 'close' e 'volatility' proprio come nel training
                feat_matrix = df_last_30[['close', 'volatility']].to_numpy(dtype=np.float32)
                asset_features.append(feat_matrix)
                
            # asset_features è una lista di 17 matrici (30, 2)
            # Dobbiamo concatenarle sull'asse 1 (le feature) per ottenere (30, 34)
            obs = np.concatenate(asset_features, axis=1)
            
            # PPO si aspetta (Batch, Window, Features) -> aggiungiamo la dimensione batch
            # ma il metodo predict() di default gestisce automaticamente un singolo sample se l'env non è vettorizzato,
            # però passando un numpy array grezzo conviene assicurarci della forma (30, 34) 
            
            action, _ = model.predict(obs, deterministic=True)
            
            logger.info(f"⚡ Titano ha deciso: {action}")
            
            # action è un array [17] con valori 0 (Short), 1 (Flat), 2 (Long)
            for i, ticker in enumerate(ASSETS):
                act_val = action[i]
                epic = get_capital_epic(ticker)
                
                direction = "FLAT"
                if act_val == 0: direction = "SELL"
                elif act_val == 2: direction = "BUY"
                
                if direction != "FLAT":
                    # Pubblica la richiesta di Audit
                    req = {
                        "epic": epic,
                        "direction": direction,
                        "size_pct": 5.0, # Dimensione fissa pilot per ora
                        "leverage": 1,
                        "prob": 0.99, # Titano deterministico
                        "source": "TITANO_V4"
                    }
                    await r.publish("audit_requests", json.dumps(req))
                    logger.info(f"Inviata richiesta Audit per {epic}: {direction}")
                    
        except Exception as e:
            logger.error(f"Errore nel loop di Titano: {e}")
            
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V4_OcchiAperti.zip")
    
    # 1. Trigger Apprendimento a Caldo (Startup)
    perform_online_learning(model_path)
    
    # 2. Schedulazione Notturna (Mezzanotte)
    schedule_nightly_learning(model_path)
    
    # 3. Avvio Loop di Trading
    asyncio.create_task(titano_loop())

@app.get("/")
def health_check():
    return {"status": "online", "message": "Titano V4 Node Running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
