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
from collections import deque
from datetime import datetime
import ta

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

class LiveFeatureNormalizer:
    """
    Gestisce la normalizzazione Z-Score in tempo reale delle 12 features.
    Mantiene in memoria gli ultimi 70 tick per calcolare statistiche rolling accurate,
    e gestisce il FrameStack a 4 livelli per il modello PPO V8.3.
    """
    def __init__(self, window_size=70, frame_stack_size=4, num_features=12):
        self.window_size = window_size
        self.frame_stack_size = frame_stack_size
        self.num_features = num_features
        
        # Buffer storico per calcolare Media e Dev_Std (ultimi 70 tick)
        self.history_buffer = deque(maxlen=window_size)
        
        # FrameStack finale per il modello (ultimi 4 tick normalizzati)
        # Inizializzato con zeri per i primi tick a mercato freddo
        self.frame_stack = deque(
            [np.zeros(num_features, dtype=np.float32) for _ in range(frame_stack_size)], 
            maxlen=frame_stack_size
        )

    def _update_historical_buffer(self, raw_features: np.ndarray):
        """Aggiunge l'ultimo tick grezzo al buffer storico."""
        self.history_buffer.append(raw_features)

    def _get_rolling_stats(self):
        """Calcola media e deviazione standard sugli ultimi N tick in memoria."""
        if len(self.history_buffer) == 0:
            return np.zeros(self.num_features), np.ones(self.num_features)
            
        history_array = np.array(self.history_buffer)
        
        rolling_mean = np.mean(history_array, axis=0)
        rolling_std = np.std(history_array, axis=0)
        
        # Evitiamo la divisione per zero se una feature è costante (es: PnL a zero all'inizio)
        rolling_std = np.where(rolling_std == 0, 1e-8, rolling_std) 
        
        return rolling_mean, rolling_std

    def process_new_tick(self, current_raw_features: np.ndarray) -> np.ndarray:
        """
        Riceve l'array delle 12 features grezze, aggiorna le statistiche,
        normalizza il dato, lo inserisce nel FrameStack e restituisce l'input da 48 elementi per PPO.
        """
        # 1. Assicuriamoci che l'input sia corretto
        assert len(current_raw_features) == self.num_features, f"Errore: attese {self.num_features} features, ricevute {len(current_raw_features)}"
        
        # 2. Aggiorniamo il buffer storico con il dato grezzo
        self._update_historical_buffer(current_raw_features)
        
        # 3. Calcoliamo la media e std dev attuali
        rolling_mean, rolling_std = self._get_rolling_stats()
        
        # 4. Z-Score Normalization del tick attuale
        normalized_tick = (current_raw_features - rolling_mean) / rolling_std
        
        # OPZIONALE MA CONSIGLIATO: Clipping dei valori estremi (come fa Stable Baselines di base)
        # Tagliamo anomalie oltre +/- 10 per non far esplodere la rete
        normalized_tick = np.clip(normalized_tick, -10.0, 10.0) 
        
        # 5. Inseriamo il tick normalizzato nel FrameStack (che butta fuori il più vecchio in automatico)
        self.frame_stack.append(normalized_tick)
        
        # 6. Appiattiamo il FrameStack in un array 1D da 48 elementi (4x12)
        # Questo è l'osservazione esatta che il modello PPO si aspetta in inferenza
        ppo_observation = np.concatenate(self.frame_stack)
        
        return ppo_observation

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
    logger.info("Avviato Titano Engine (V8.3 Sniper)...")
    
    try:
        model_path = os.path.join(os.path.dirname(__file__), "models", "Titano_V83_Crypto.zip")
        model = PPO.load(model_path)
        logger.info("🧠 Modello Titano V8.3 (Sniper) caricato con successo!")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
        return

    r = await aioredis.from_url(REDIS_URL)
    api.authenticate()

    pubsub = r.pubsub()
    await pubsub.subscribe("market_updates")
    
    logger.info("📡 In attesa di dati in streaming da Market Streamer Engine (V8)...")
    
    # Inizializziamo i normalizzatori per ogni asset
    normalizers = {}
    
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
                        model = PPO.load(model_path)
                        last_model_mtime = current_mtime
                        logger.info("✅ HOT RELOAD COMPLETATO: Titano sta usando i nuovi pesi neurali V8.3!")
                    except Exception as e:
                        logger.error(f"❌ Errore durante l'Hot Reload, continuo con il vecchio cervello: {e}")
                        
            try:
                data = json.loads(message['data'])
                # data è un dizionario: { epic: [70 candele], epic2: [70 candele] }
                
                batch_obs = []
                valid_assets = []
                
                for epic, candles in data.items():
                    if len(candles) < 70: 
                        continue
                        
                    if epic not in normalizers:
                        normalizers[epic] = LiveFeatureNormalizer()
                        
                    # Calcoliamo ATR e Momentum sull'intero storico
                    df = pd.DataFrame(candles) # 'open', 'high', 'low', 'close'
                    df['Log_Return'] = np.log(df['close'] / df['close'].shift(1))
                    df['Mom_50'] = df['close'] / df['close'].shift(50) - 1
                    
                    atr_ind = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
                    df['ATR'] = atr_ind.average_true_range()
                    df['ATR_Z_Score'] = (df['ATR'] - df['ATR'].rolling(50).mean()) / (df['ATR'].rolling(50).std() + 1e-8)
                    
                    # Prendiamo l'ultima riga calcolata
                    last_row = df.iloc[-1]
                    log_ret = float(last_row.get('Log_Return', 0.0))
                    atr_z = float(last_row.get('ATR_Z_Score', 0.0))
                    mom_50 = float(last_row.get('Mom_50', 0.0))
                    
                    try:
                        xgb_val = await r.get(f"xgboost_prob:{epic}")
                        xgb_prob = float(xgb_val) if xgb_val else 0.5
                    except: xgb_prob = 0.5
                    
                    try:
                        is_crypto = any(c in epic for c in ["BTC", "ETH", "SOL", "DOGE", "XRP"])
                        news_val = await r.get(f"cryptobert_sentiment:{epic}" if is_crypto else f"finbert_sentiment:{epic}")
                        bert_ema = float(news_val) if news_val else 0.0
                    except: bert_ema = 0.0
                    
                    tsn_scaled = 0.0 # Time Since News (Fallback live)
                    
                    pos = 0.0
                    pnl_pct = 0.0
                    for p in portfolio_state_cache.get("open_positions", []):
                        if p.get("epic") == epic:
                            pos = 1.0 if p.get("position", {}).get("direction") == "BUY" else -1.0
                            entry = float(p.get("position", {}).get("level", 0.0))
                            if entry > 0:
                                pnl_pct = ((float(last_row['close']) - entry) / entry) * pos
                                
                    now = datetime.utcnow()
                    curr_min = now.hour * 60 + now.minute
                    t_sin = float(np.sin(curr_min * (2. * np.pi / 1440.)))
                    t_cos = float(np.cos(curr_min * (2. * np.pi / 1440.)))
                    d_sin = float(np.sin(now.weekday() * (2. * np.pi / 7.)))
                    d_cos = float(np.cos(now.weekday() * (2. * np.pi / 7.)))
                    
                    # Costruzione del vettore grezzo esatto (12 features)
                    raw_features = np.array([log_ret, atr_z, mom_50, bert_ema, tsn_scaled, xgb_prob, pos, pnl_pct, t_sin, t_cos, d_sin, d_cos], dtype=np.float32)
                    
                    # Evitiamo NaN spuri iniziali
                    raw_features = np.nan_to_num(raw_features, nan=0.0)
                    
                    # La classe gestisce la memoria, la normalizzazione Z-Score rolling e il FrameStack (4 livelli -> 48 dims)
                    ppo_obs = normalizers[epic].process_new_tick(raw_features)
                    
                    batch_obs.append(ppo_obs)
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
                            action_log = "ACCUMULO (Pyramiding)" if is_owned else "NUOVA POSIZIONE"
                            logger.info(f"🧠 [TITANO V8] {epic} -> {direction} ({action_log}) (Confidence: {confidence*100:.1f}%)")
                            
                            req = {
                                "epic": epic, "direction": direction, "size_pct": dynamic_size, "leverage": 1, 
                                "prob": confidence, "xgb_prob": float(xgb_prob), "news_sentiment": float(news_sentiment),
                                "source": f"TITANO_V8_{'ACCUMULO' if is_owned else 'NUOVO'}"
                            }
                            await r.publish("execution_requests", json.dumps(req))
                            await r.publish("audit_requests", json.dumps(req))
                        else:
                            # Invia segnale FLAT anche al worker per chiudere eventuali posizioni
                            logger.info(f"🧠 [TITANO V8] {epic} -> {direction} (Confidence: {confidence*100:.1f}%)")
                            req = {"epic": epic, "direction": "FLAT", "size_pct": 0, "prob": confidence, "source": "TITANO_V8_FLAT"}
                            await r.publish("execution_requests", json.dumps(req))
                            await r.publish("audit_requests", json.dumps(req))
            except Exception as e:
                logger.error(f"Errore inferenza streaming: {e}")

async def system_commands_loop():
    logger.info("📡 In ascolto per comandi di sistema (Redis)...")
    try:
        r = await aioredis.from_url(REDIS_URL)
        pubsub = r.pubsub()
        await pubsub.subscribe("system_commands")
        async for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    if data.get("command") == "force_gym":
                        logger.info("🔥 Ricevuto comando remoto: FORZA ADDESTRAMENTO IN CORSO!")
                        import threading
                        threading.Thread(target=perform_online_learning).start()
                except Exception as e:
                    logger.error(f"Errore parsing system command: {e}")
    except Exception as e:
        logger.error(f"Errore Redis in system_commands_loop: {e}")

def download_model_from_drive(model_path: str):
    url = f"https://drive.google.com/uc?id={V6_DRIVE_FILE_ID}"
    logger.info(f"Avvio download del modello V6 da Google Drive ({url})...")
    try:
        gdown.download(url, model_path, quiet=False)
        logger.info("Download del modello completato con successo!")
    except Exception as e:
        logger.error(f"Errore durante il download del modello: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info("Inizializzazione Titano Engine V8.3...")
    
    # 1. Start-up: Online Learning dai trade passati
    # perform_online_learning()
    
    # 2. Schedulazione Notturna (Mezzanotte)
    schedule_nightly_learning()
    
    # 3. Avvio Sync Portafoglio
    asyncio.create_task(portfolio_sync_loop())
    
    # 4. Avvio Loop Comandi di Sistema (per il pulsante Dashboard)
    asyncio.create_task(system_commands_loop())
    
    # 5. Avvio Loop di Trading
    asyncio.create_task(titano_loop())

@app.get("/")
def health_check():
    return {"status": "online", "message": "Titano V6 Node Running"}

@app.get("/force_gym")
def force_gym():
    import threading
    threading.Thread(target=perform_online_learning).start()
    return {"status": "Palestra manuale avviata in background! Controlla i log su Railway per vedere i progressi dell'addestramento."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
# Force Railway Deploy
