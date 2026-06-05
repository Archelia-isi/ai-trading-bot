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

portfolio_state_cache = {"open_positions": []}

async def portfolio_sync_loop():
    logger.info("Avviato sync del portafoglio per Titano...")
    r = await aioredis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("portfolio_status")
    async for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                data = json.loads(message['data'])
                portfolio_state_cache["open_positions"] = data.get("open_positions", [])
            except Exception as e:
                logger.error(f"Errore lettura portfolio_status in Titano: {e}")

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
                net_arch=dict(pi=[2048, 2048, 1024], vf=[2048, 2048, 1024])
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

    pubsub = r.pubsub()
    await pubsub.subscribe("market_updates")
    
    logger.info("📡 In attesa di dati in streaming da Market Streamer Engine (V6)...")
    
    # HOT-RELOAD TRACKER
    last_model_mtime = os.path.getmtime(model_path) if os.path.exists(model_path) else 0
    
    async for message in pubsub.listen():
        if message['type'] == 'message':
            # Controllo Hot-Reload del cervello
            if os.path.exists(model_path):
                current_mtime = os.path.getmtime(model_path)
                if current_mtime > last_model_mtime:
                    logger.info("🔥 HOT RELOAD: Trovato un nuovo cervello aggiornato! Iniezione in corso...")
                    try:
                        if not USIAMO_LA_V6:
                            model = PPO.load(model_path, custom_objects={'MultiAssetFeatureExtractor': MultiAssetFeatureExtractor})
                        else:
                            model = PPO.load(
                                model_path, 
                                custom_objects={
                                    'EstrazioneCaratteristiche': EstrazioneCaratteristiche,
                                    'policy_kwargs': policy_kwargs
                                }
                            )
                        last_model_mtime = current_mtime
                        logger.info("✅ HOT RELOAD COMPLETATO: Titano sta usando i nuovi pesi neurali!")
                    except Exception as e:
                        logger.error(f"❌ Errore durante l'Hot Reload, continuo con il vecchio cervello: {e}")
                        
            try:
                data = json.loads(message['data'])
                # data è un dizionario: { epic: [30 candele], epic2: [30 candele] }
                
                batch_obs = []
                valid_assets = []
                
                for epic, candles in data.items():
                    if len(candles) < 30: 
                        continue
                        
                    closes = np.array([c.get('close', 0.0) for c in candles])
                    df = pd.DataFrame({'close': closes})
                    df['returns'] = df['close'].pct_change()
                    df['volatility'] = df['returns'].rolling(window=20).std()
                    df.fillna(0, inplace=True)
                    
                    try:
                        xgb_val = await r.get(f"xgboost_prob:{epic}")
                        xgb_prob = float(xgb_val) if xgb_val else 0.5
                    except: xgb_prob = 0.5
                    
                    try:
                        is_crypto = any(c in epic for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"])
                        news_val = await r.get(f"cryptobert_sentiment:{epic}" if is_crypto else f"finbert_sentiment:{epic}")
                        news_sentiment = float(news_val) if news_val else 0.0
                    except: news_sentiment = 0.0
                    
                    df['xgb_proxy'] = xgb_prob
                    df['news_proxy'] = news_sentiment
                    
                    df_last_30 = df.iloc[-30:]
                    feat_matrix = df_last_30[['returns', 'volatility', 'xgb_proxy', 'news_proxy']].to_numpy(dtype=np.float32)
                    
                    batch_obs.append(feat_matrix)
                    valid_assets.append(epic)
                
                if len(batch_obs) > 0:
                    obs_tensor = np.stack(batch_obs)
                    azioni, _ = model.predict(obs_tensor, deterministic=True)
                    
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
                        
                        
                        is_owned = any(p.get("epic") == epic for p in portfolio_state_cache.get("open_positions", []))
                        
                        if direction != "FLAT":
                            dynamic_size = round(confidence * 10.0, 2)
                            
                            # Se lo possediamo già e Titano dice BUY, è un ACCUMULO.
                            action_log = "ACCUMULO (Pyramiding)" if is_owned else "NUOVA POSIZIONE"
                            logger.info(f"🧠 [TITANO V6] {epic} -> {direction} ({action_log}) (Confidence: {confidence*100:.1f}%)")
                            
                            req = {
                                "epic": epic, "direction": direction, "size_pct": dynamic_size, "leverage": 1, 
                                "prob": confidence, "xgb_prob": float(xgb_prob), "news_sentiment": float(news_sentiment),
                                "source": f"TITANO_V6_{'ACCUMULO' if is_owned else 'NUOVO'}"
                            }
                            await r.publish("execution_requests", json.dumps(req))
                            await r.publish("audit_requests", json.dumps(req))
                        else:
                            logger.info(f"🧠 [TITANO V6] {epic} -> {direction} (Confidence: {confidence*100:.1f}%)")
                            req_ui = {"epic": epic, "direction": "FLAT", "size_pct": 0, "prob": confidence, "source": "TITANO_V6_SUPREMO"}
                            await r.publish("audit_requests", json.dumps(req_ui))
            except Exception as e:
                logger.error(f"Errore inferenza streaming: {e}")

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
    
    # 3. Avvio Sync Portafoglio
    asyncio.create_task(portfolio_sync_loop())
    
    # 4. Avvio Loop di Trading
    asyncio.create_task(titano_loop())

@app.get("/")
def health_check():
    return {"status": "online", "message": "Titano V6 Node Running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Force Railway Deploy
