import os
import time
import redis
import xgboost as xgb
import numpy as np
import pandas as pd
import ccxt
from dotenv import load_dotenv

load_dotenv()

print("Avvio Demone XGBoost...")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    print("Connessione a Redis stabilita per il Worker XGBoost.")
except Exception as e:
    print(f"Errore critico di connessione a Redis: {e}")
    raise e

percorso_modello = os.getenv("XGB_MODEL_PATH", "/app/models/xgb_model.json")
caricato = False
try:
    modello = xgb.XGBClassifier()
    modello.load_model(percorso_modello)
    caricato = True
    print(f"Modello XGBoost caricato con successo da {percorso_modello}")
except Exception as e:
    print(f"Avviso: Modello XGBoost non trovato in {percorso_modello}. Verrà generato un valore neutrale (0.5). Dettaglio: {e}")

exchange = ccxt.kucoin({'enableRateLimit': True})

while True:
    try:
        candele = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=2)
        
        if len(candele) >= 2:
            chiusura_precedente = candele[-2][4]
            prezzo_attuale = candele[-1][4]
            
            ritorno_logaritmico = np.log(prezzo_attuale / chiusura_precedente)
            
            if caricato:
                df_inferenza = pd.DataFrame({'Log_Return': [ritorno_logaritmico]})
                probabilita = modello.predict_proba(df_inferenza)[0][1]
            else:
                probabilita = 0.5
                
            r.set('live_xgb_prob', float(probabilita))
            print(f"[Sistema XGB] Prezzo: {prezzo_attuale} | Ritorno Logaritmico: {ritorno_logaritmico:.5f} | Probabilità Rialzista: {probabilita:.3f}")
        else:
            print("Avviso: L'exchange non ha restituito candele sufficienti.")
            
    except Exception as e:
        print(f"Errore di rete o di elaborazione nel ciclo XGB: {e}. Attendo il prossimo ciclo.")
        
    time.sleep(60)
