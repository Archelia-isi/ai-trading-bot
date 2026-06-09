import os
import time
import redis
import xgboost as xgb
import numpy as np
import pandas as pd
import ccxt

print("🌲 Avvio XGBoost Worker Daemon...")

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(redis_url, decode_responses=True)
    r.ping()
    print("✅ Connesso a Redis per XGB Worker")
except Exception as e:
    print(f"❌ Impossibile connettersi a Redis ({redis_url}): {e}")
    exit(1)

model_path = os.path.join(os.path.dirname(__file__), '../../models/xgb_model.json')
model_loaded = False
try:
    model = xgb.XGBClassifier()
    model.load_model(model_path)
    model_loaded = True
    print("✅ Modello XGBoost caricato")
except:
    print("⚠️ Modello XGBoost non trovato, emetterò probabilità neutre (0.5).")

exchange = ccxt.kucoin()

while True:
    try:
        # Recupera ultime candele M15
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=2)
        if len(ohlcv) >= 2:
            close_prev = ohlcv[-2][4]
            close_curr = ohlcv[-1][4]
            log_ret = np.log(close_curr / close_prev)
            
            if model_loaded:
                df_inf = pd.DataFrame({'Log_Return': [log_ret]})
                prob = model.predict_proba(df_inf)[0][1]
            else:
                prob = 0.5
                
            r.set('live_xgb_prob', float(prob))
            print(f"🌲 [XGB] LogRet: {log_ret:.4f} | Prob: {prob:.3f}")
            
    except Exception as e:
        print(f"⚠️ Errore XGB Worker: {e}")
        
    time.sleep(60) # Allineato col minuto
