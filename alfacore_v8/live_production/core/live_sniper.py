import os
import sys
import time
import redis
import ccxt
import numpy as np
from collections import deque
from datetime import datetime, timezone
from stable_baselines3 import PPO

# Aggiunge root al path per importare neon_db_manager
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.neon_db_manager import NeonDBManager

print("🎯 Inizializzazione Live Sniper V8 (Paper Trading)...")

# 1. Connessioni DB e Redis
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()
except Exception as e:
    print(f"❌ Impossibile connettersi a Redis ({redis_url}): {e}")
    exit(1)

db = NeonDBManager()

# 2. Caricamento Cervello PPO
model_path = os.path.join(os.path.dirname(__file__), '../../models/crypto_v8_best.zip')
if not os.path.exists(model_path):
    print(f"⚠️ Modello {model_path} non trovato. Fallback su dummy inferenza.")
    model = None
else:
    model = PPO.load(model_path)
    print("✅ Cervello PPO Caricato e Operativo.")

exchange = ccxt.kucoin()
MAX_SIZE = 0.05
BASE_SPREAD = 0.0020
MAX_BARS = 16 # Per lo scaling del time since news
n_stack = 10
obs_dim = 12

# Stato simulato
sim_balance = 10000.0
sim_position = 0
sim_entry_price = 0.0
frame_stack = deque([np.zeros(obs_dim, dtype=np.float32) for _ in range(n_stack)], maxlen=n_stack)

def get_live_observation(close_price, log_ret, tr, mom_50):
    sentiment_ema = float(r.get('live_crypto_sentiment') or 0.0)
    bars_since_news = int(r.get('crypto_bars_since_news') or 0)
    xgb_prob = float(r.get('live_xgb_prob') or 0.5)
    
    time_since_scaled = np.exp(-bars_since_news / (MAX_BARS / 2))
    
    dt = datetime.now(timezone.utc)
    ora_decimale = dt.hour + dt.minute / 60.0
    time_sin = np.sin(ora_decimale * (2. * np.pi / 24.))
    time_cos = np.cos(ora_decimale * (2. * np.pi / 24.))
    
    giorno_settimana = dt.weekday()
    day_sin = np.sin(giorno_settimana * (2. * np.pi / 7.))
    day_cos = np.cos(giorno_settimana * (2. * np.pi / 7.))
    
    pnl_latente_pct = 0.0
    if sim_position != 0 and sim_entry_price > 0:
        size_investita = sim_balance * MAX_SIZE
        variazione_pct = (close_price - sim_entry_price) / sim_entry_price
        pnl_val = size_investita * variazione_pct * sim_position
        pnl_latente_pct = pnl_val / sim_balance
        
    obs = np.array([
        log_ret, tr, mom_50, sentiment_ema, time_since_scaled, xgb_prob,
        float(sim_position), pnl_latente_pct, time_sin, time_cos, day_sin, day_cos
    ], dtype=np.float32)
    
    snapshot = {
        "sentiment_ema": sentiment_ema,
        "xgb_prob": xgb_prob,
        "pnl_latente_pct": pnl_latente_pct,
        "log_ret": log_ret
    }
    return obs, snapshot

# 3. Bootstrap Frame Stacking
print("🔄 Allineamento memoria spaziale (ultime 50 candele)...")
try:
    history = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=50)
    closes = [x[4] for x in history]
    for i in range(10):
        idx = -10 + i
        c_prev = closes[idx-1]
        c_curr = closes[idx]
        l_ret = np.log(c_curr / c_prev)
        mom = c_curr / closes[idx-50] - 1 if (idx-50)>= -len(closes) else 0.0
        obs, _ = get_live_observation(c_curr, l_ret, 0.0, mom)
        frame_stack.append(obs)
except Exception as e:
    print(f"⚠️ Errore bootstrap: {e}")

print("⚡ Sniper armato. Entro in ascolto sul mercato...")

# 4. Main Loop
while True:
    now = datetime.now(timezone.utc)
    # Esegue solo al minuto 00, 15, 30, 45
    if now.minute % 15 == 0 and now.second < 5:
        try:
            ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=50)
            close_prev = ohlcv[-2][4]
            close_curr = ohlcv[-1][4]
            high_curr = ohlcv[-1][2]
            low_curr = ohlcv[-1][3]
            
            l_ret = np.log(close_curr / close_prev)
            tr = high_curr - low_curr
            mom = close_curr / ohlcv[0][4] - 1
            
            obs, audit_snap = get_live_observation(close_curr, l_ret, tr, mom)
            frame_stack.append(obs)
            stacked_obs = np.concatenate(frame_stack)
            
            # Inferenza
            if model:
                action, _ = model.predict(stacked_obs, deterministic=True)
                mapped_action = 0 if action == 0 else (1 if action == 1 else -1)
            else:
                mapped_action = 0 # Fallback flat se manca il cervello
                
            # Paper Trading Execution
            slippage_paid = 0.0
            action_str = "FLAT" if mapped_action == 0 else ("LONG" if mapped_action == 1 else "SHORT")
            
            if mapped_action != sim_position:
                moltiplicatore = np.random.uniform(1.0, 1.5)
                if sim_position != 0 and mapped_action != 0:
                    moltiplicatore *= 2.0
                
                slippage_paid = (sim_balance * MAX_SIZE) * (BASE_SPREAD * moltiplicatore)
                
                if sim_position != 0:
                    size = sim_balance * MAX_SIZE
                    var_pct = (close_curr - sim_entry_price) / sim_entry_price
                    sim_balance += size * var_pct * sim_position
                
                sim_balance -= slippage_paid
                sim_entry_price = close_curr if mapped_action != 0 else 0.0
                sim_position = mapped_action
                
                print(f"[{now.strftime('%H:%M:%S')}] 🚨 ORDINE: {action_str} | Equity: {sim_balance:.2f} | Prezzo: {close_curr}")
                db.log_trade_action(action_str, audit_snap, sim_entry_price, slippage_paid, sim_balance)
            else:
                print(f"[{now.strftime('%H:%M:%S')}] HOLD: {action_str} | Equity Latente: {sim_balance:.2f}")
                
            time.sleep(60) # Pausa lunga per evitare multipli esecuzioni nello stesso minuto
            
        except Exception as e:
            print(f"⚠️ Errore Sniper Loop: {e}")
            
    time.sleep(1) # Micro-sleep
