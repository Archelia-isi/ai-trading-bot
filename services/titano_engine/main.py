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
    def __init__(self, window_size=70, frame_stack_size=4, num_features=16):
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
        Riceve l'array delle 16 features grezze, aggiorna le statistiche,
        normalizza il dato, lo inserisce nel FrameStack e restituisce l'input da 64 elementi per PPO.
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
        model_path = os.path.join(os.path.dirname(__file__), "models", "Crypto_V8_Scalp_10M_Master.zip")
        # Fallback a DQN se il modello non supporta use_sde (modelli salvati in DQN non accettano parametri PPO/SAC)
        custom_objects = {
            "use_sde": False,
        }
        try:
            model = PPO.load(model_path, custom_objects=custom_objects)
        except TypeError:
            from stable_baselines3 import DQN
            model = DQN.load(model_path, custom_objects=custom_objects)
            
        logger.info("[SUCCESS] Cervello Master caricato correttamente da AI_Master_Brain.zip")
    except Exception as e:
        logger.error(f"Errore caricamento modello: {e}")
        return

    r = await aioredis.from_url(REDIS_URL)
    api.authenticate()

    pubsub = r.pubsub()
    await pubsub.subscribe("market_updates_crypto")
    
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
                xgb_probs_map = {} # FIX BUG VISIVO DEL 47%
                
                for epic, candles in data.items():
                    if len(candles) < 70: 
                        continue
                        
                    # ====================================================
                    # ALFACORE CRYPTO (Titano V8.3)
                    # Elabora tutti gli asset ricevuti dal canale
                    # ====================================================
                        
                    if epic not in normalizers:
                        normalizers[epic] = LiveFeatureNormalizer()
                        
                    # === 16 FEATURES MASTER BLUPEPRINT ===
                    df = pd.DataFrame(candles) # 'open', 'high', 'low', 'close', 'volume'
                    
                    # 1. Log_Return_Norm
                    df['Log_Return_Norm'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1)
                    
                    # 2. Volume_Norm
                    if 'volume' in df.columns:
                        df['Rolling_Mean_Vol_50'] = df['volume'].rolling(50).mean()
                        df['Rolling_Std_Vol_50'] = df['volume'].rolling(50).std() + 1e-8
                        df['Volume_Norm'] = (df['volume'] - df['Rolling_Mean_Vol_50']) / df['Rolling_Std_Vol_50']
                    else:
                        df['Volume_Norm'] = 0.0
                    
                    # 3. Volatility_Recente (ATR)
                    atr_ind = ta.volatility.AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
                    df['ATR'] = atr_ind.average_true_range()
                    
                    # 5. Regime_Market (-1, 0, 1 basato su SMA 50)
                    df['SMA_50'] = df['close'].rolling(50).mean()
                    df['Regime_Market'] = np.where(df['close'] > df['SMA_50'] * 1.001, 1.0, np.where(df['close'] < df['SMA_50'] * 0.999, -1.0, 0.0))
                    
                    # 6. Z_Score_ATR
                    df['Rolling_Mean_ATR_50'] = df['ATR'].rolling(50).mean()
                    df['Rolling_Std_ATR_50'] = df['ATR'].rolling(50).std() + 1e-8
                    df['Z_Score_ATR'] = (df['ATR'] - df['Rolling_Mean_ATR_50']) / df['Rolling_Std_ATR_50']
                    
                    # 7. Dist_SMA
                    df['Dist_SMA'] = (df['close'] - df['SMA_50']) / df['SMA_50']
                    
                    # 8. Mom_Fast (RSI / 100)
                    rsi_ind = ta.momentum.RSIIndicator(close=df['close'], window=14)
                    df['Mom_Fast'] = rsi_ind.rsi() / 100.0
                    
                    # 9. Mom_Slow_Z
                    df['ROC_50'] = (df['close'] - df['close'].shift(50)) / df['close'].shift(50)
                    df['Rolling_Mean_ROC_50'] = df['ROC_50'].rolling(50).mean()
                    df['Rolling_Std_ROC_50'] = df['ROC_50'].rolling(50).std() + 1e-8
                    df['Mom_Slow_Z'] = (df['ROC_50'] - df['Rolling_Mean_ROC_50']) / df['Rolling_Std_ROC_50']
                    
                    # Prendiamo l'ultima riga calcolata
                    last_row = df.iloc[-1]
                    
                    f1 = float(last_row.get('Log_Return_Norm', 0.0))
                    f2 = float(last_row.get('Volume_Norm', 0.0))
                    f3 = float(last_row.get('ATR', 0.0))
                    
                    # 4. XGB_Prob (Oracolo)
                    try:
                        xgb_val = await r.get(f"xgboost_prob:{epic}")
                        xgb_prob = float(xgb_val) if xgb_val else 0.5
                    except: xgb_prob = 0.5
                    f4 = xgb_prob
                    xgb_probs_map[epic] = xgb_prob # Salviamo il prob per questo epic specifico
                    
                    f5 = float(last_row.get('Regime_Market', 0.0))
                    f6 = float(last_row.get('Z_Score_ATR', 0.0))
                    f7 = float(last_row.get('Dist_SMA', 0.0))
                    f8 = float(last_row.get('Mom_Fast', 0.5))
                    f9 = float(last_row.get('Mom_Slow_Z', 0.0))
                    
                    # 10, 11: Time Sine & Cosine
                    now = datetime.utcnow()
                    curr_min = now.hour * 60 + now.minute
                    f10 = float(np.sin(curr_min * (2. * np.pi / 1440.)))
                    f11 = float(np.cos(curr_min * (2. * np.pi / 1440.)))
                    
                    # 12, 13, 14, 15: Posizione Corrente e Stato
                    f12_pos = 0.0
                    f13_pnl = 0.0
                    f14_time_in_trade = 0.0
                    f15_max_dd = 0.0
                    
                    for p in portfolio_state_cache.get("open_positions", []):
                        if p.get("epic") == epic:
                            direction = p.get("direction", p.get("position", {}).get("direction", "FLAT"))
                            f12_pos = 1.0 if direction == "BUY" else -1.0
                            entry = float(p.get("level", p.get("position", {}).get("level", 0.0)))
                            if entry > 0:
                                f13_pnl = ((float(last_row['close']) - entry) / entry) * f12_pos
                            f14_time_in_trade = float(p.get("time_in_trade", 0.0))
                            f15_max_dd = float(p.get("max_drawdown", 0.0))
                    
                    # 16. Step Index Norm
                    f16_step_index = 0.5
                    
                    # Manteniamo news_sentiment a 0.0 solo per non far crashare i logger successivi
                    news_sentiment = 0.0
                    
                    # Costruzione del vettore grezzo esatto (16 features in perfetto ordine)
                    raw_features = np.array([f1, f2, f3, f4, f5, f6, f7, f8, f9, f10, f11, f12_pos, f13_pnl, f14_time_in_trade, f15_max_dd, f16_step_index], dtype=np.float32)
                    
                    # Evitiamo NaN spuri iniziali
                    raw_features = np.nan_to_num(raw_features, nan=0.0)
                    
                    # La classe gestisce la memoria, la normalizzazione Z-Score rolling e il FrameStack (4 livelli -> 64 dims)
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
                        
                        correct_xgb_prob = xgb_probs_map.get(epic, 0.5)
                        
                        if direction != "FLAT":
                            if confidence < 0.70:
                                logger.info(f"🛑 [TITANO V8] {epic} -> {direction} SCARTATO (Confidence {confidence*100:.1f}% < 70.0%). Forzato a FLAT.")
                                direction = "FLAT"
                        
                        if direction != "FLAT":
                            dynamic_size = round(confidence * 10.0, 2)
                            action_log = "ACCUMULO (Pyramiding)" if is_owned else "NUOVA POSIZIONE"
                            logger.info(f"🧠 [TITANO V8] {epic} -> {direction} ({action_log}) (Confidence: {confidence*100:.1f}%)")
                            
                            req = {
                                "epic": epic, "direction": direction, "size_pct": dynamic_size, "leverage": 1, 
                                "prob": confidence, "xgb_prob": float(correct_xgb_prob), "news_sentiment": float(news_sentiment),
                                "source": f"TITANO_V8_SCALP_{'ACCUMULO' if is_owned else 'NUOVO'}"
                            }
                            await r.publish("execution_requests", json.dumps(req))
                            await r.publish("audit_requests", json.dumps(req))
                        else:
                            # Invia segnale FLAT anche al worker per chiudere eventuali posizioni
                            logger.info(f"🧠 [TITANO V8] {epic} -> {direction} (Confidence: {confidence*100:.1f}%)")
                            req = {"epic": epic, "direction": "FLAT", "size_pct": 0, "prob": confidence, "source": "TITANO_V8_SCALP_FLAT"}
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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
# Force Railway Deploy
