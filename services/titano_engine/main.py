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
import gdown

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

# --- CLASSE CUSTOM V6 ---
class EstrazioneCaratteristiche(BaseFeaturesExtractor):
    def __init__(self, observation_space: gym.spaces.Box, dimensione_caratteristiche: int = 2048):
        super().__init__(observation_space, dimensione_caratteristiche)
        self.rete_visiva = nn.Sequential(
            nn.Conv1d(4, 256, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(256, 512, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool1d(2),
            nn.Conv1d(512, 1024, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Flatten()
        )
        with torch.no_grad():
            campione = torch.zeros(1, 4, observation_space.shape[0])
            dim_appiattita = self.rete_visiva(campione).shape[1]
            
        self.cervello_logico = nn.Sequential(
            nn.Linear(dim_appiattita, dimensione_caratteristiche),
            nn.ReLU()
        )

    def forward(self, osservazioni: torch.Tensor) -> torch.Tensor:
        x = osservazioni.permute(0, 2, 1)
        return self.cervello_logico(self.rete_visiva(x))

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
USIAMO_LA_V6 = True

async def titano_loop():
    logger.info(f"Avviato Titano Engine (V6={USIAMO_LA_V6})...")
    
    import __main__
    setattr(__main__, 'MultiAssetFeatureExtractor', MultiAssetFeatureExtractor)
    setattr(__main__, 'EstrazioneCaratteristiche', EstrazioneCaratteristiche)
    
    try:
        if not USIAMO_LA_V6:
            model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V5_OcchiAperti.zip")
            model = PPO.load(model_path, custom_objects={'MultiAssetFeatureExtractor': MultiAssetFeatureExtractor})
            logger.info("🧠 Modello Titano V5 caricato con successo!")
        else:
            model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V6_Universale.zip")
            
            # Ricostruiamo i kwargs della V6 Supremo per bypassare i bug di deserializzazione
            policy_kwargs = dict(
                features_extractor_class=EstrazioneCaratteristiche,
                features_extractor_kwargs=dict(dimensione_caratteristiche=2048),
                net_arch=dict(pi=[2048, 2048], vf=[2048, 2048])
            )
            
            model = PPO.load(
                model_path, 
                custom_objects={
                    'EstrazioneCaratteristiche': EstrazioneCaratteristiche,
                    'policy_kwargs': policy_kwargs
                }
            )
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
                    feat_matrix = df_last_30[['returns', 'volatility']].to_numpy(dtype=np.float32)
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
                    
                    # Recupero Parere XGBoost
                    try:
                        xgb_val = await r.get(f"xgboost_prob:{epic}")
                        xgb_prob = float(xgb_val) if xgb_val else 0.5
                    except:
                        xgb_prob = 0.5
                    
                    # Recupero Parere News (FinBERT o CryptoBERT)
                    try:
                        is_crypto = any(c in epic for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"])
                        if is_crypto:
                            news_val = await r.get(f"cryptobert_sentiment:{epic}")
                        else:
                            news_val = await r.get(f"finbert_sentiment:{epic}")
                        news_sentiment = float(news_val) if news_val else 0.0
                    except:
                        news_sentiment = 0.0
                    
                    df['xgb_proxy'] = xgb_prob
                    df['news_proxy'] = news_sentiment
                    
                    df_last_30 = df.iloc[-30:]
                    # Ora la matrice è 30x4! Usiamo 'returns' come Prezzo_Norm dell'addestramento!
                    feat_matrix = df_last_30[['returns', 'volatility', 'xgb_proxy', 'news_proxy']].to_numpy(dtype=np.float32)
                    
                    batch_obs.append(feat_matrix)
                    valid_assets.append(epic)
                
                if len(batch_obs) > 0:
                    # Converte la lista in un Tensor 3D per l'inferenza parallela: Shape (Num_Assets, 30, 4)
                    obs_tensor = np.stack(batch_obs)
                    
                    # Inferenza Simultanea Vettorizzata
                    azioni, _ = model.predict(obs_tensor, deterministic=True)
                    
                    # Estrazione Sicurezza (Confidence)
                    with torch.no_grad():
                        obs_tensor_th = torch.as_tensor(obs_tensor, device=model.device)
                        distribution = model.policy.get_distribution(obs_tensor_th)
                        probs = distribution.distribution.probs.cpu().numpy()
                    
                    for i, epic in enumerate(valid_assets):
                        act_val = azioni[i]
                        confidence = float(probs[i][act_val])
                        
                        direction = "FLAT"
                        if act_val == 0: direction = "SELL"
                        elif act_val == 2: direction = "BUY"
                        
                        if direction != "FLAT":
                            # Calcolo Size Dinamica: Max 10% del capitale. Se confidence 90% -> 9.0%, se 51% -> 5.1%
                            dynamic_size = round(confidence * 10.0, 2)
                            
                            req = {
                                "epic": epic, 
                                "direction": direction, 
                                "size_pct": dynamic_size, 
                                "leverage": 1, 
                                "prob": confidence, 
                                "source": "TITANO_V6_SUPREMO"
                            }
                            # BYPASS AUDIT (Carta Bianca): Invia direttamente all'Esecutore
                            await r.publish("execution_requests", json.dumps(req))

        except Exception as e:
            logger.error(f"Errore nel loop di Titano: {e}")
            
        await asyncio.sleep(60)

def download_model_from_drive(model_path: str):
    file_id = "1NCRjilt5hsysIU2rHd6RsOzjZY2KqvQh"
    url = f"https://drive.google.com/uc?id={file_id}"
    logger.info(f"Avvio download del modello V6 da Google Drive ({url})...")
    try:
        gdown.download(url, model_path, quiet=False)
        logger.info("Download del modello completato con successo!")
    except Exception as e:
        logger.error(f"Errore durante il download del modello: {e}")

@app.on_event("startup")
async def startup_event():
    model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V6_Universale.zip")
    
    # 0. Download del modello pesante da Google Drive (se non esiste)
    if USIAMO_LA_V6 and not os.path.exists(model_path):
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        download_model_from_drive(model_path)
    
    # 1. Start-up: Online Learning dai trade passati
    # perform_online_learning()
    
    # 2. Schedulazione Notturna (Mezzanotte)
    schedule_nightly_learning()
    
    # 3. Avvio Loop di Trading
    asyncio.create_task(titano_loop())

@app.get("/")
def health_check():
    return {"status": "online", "message": "Titano V6 Node Running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Force Railway Deploy
