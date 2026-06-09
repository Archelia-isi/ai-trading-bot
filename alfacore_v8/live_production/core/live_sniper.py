import os
import time
import redis
import collections
import numpy as np
from stable_baselines3 import PPO
from dotenv import load_dotenv
import sys

# Aggiungi il percorso root del modulo per l'importazione
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.neon_db_manager import GestoreNeonDB

load_dotenv()

print("Inizializzazione Motore HFT (Sniper V8) a latenza zero...")

# Connessioni
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(REDIS_URL, decode_responses=True)
except Exception as e:
    print(f"Errore connessione Redis: {e}")
audit_db = GestoreNeonDB()

# Modello IA PPO
percorso_ppo = os.getenv("PPO_MODEL_PATH", "/app/models/crypto_v8_best.zip")
try:
    modello_ppo = PPO.load(percorso_ppo)
    print("Cervello neurale PPO armato.")
except Exception as e:
    print(f"Avviso: Modello PPO non trovato in {percorso_ppo}. Generazione azioni dummy per test. Dettaglio: {e}")
    modello_ppo = None

# Frame Stacking in tempo reale (Finestra mobile di 10 step come richiesto)
DIMENSIONE_FRAME = 10
memoria_osservazioni = collections.deque(maxlen=DIMENSIONE_FRAME)

def estrai_prezzi_mercato_veloce():
    """Simula estrazione iperveloce dei prezzi per il frame"""
    return np.random.rand(9)

while True:
    inizio_ciclo = time.time()
    
    # 1. Lettura a Latenza Zero da Redis (nessun calcolo pesante qui)
    sentiment = float(r.get('live_crypto_sentiment') or 0.0)
    prob_xgb = float(r.get('live_xgb_prob') or 0.5)
    minuti_news = float(r.get('crypto_bars_since_news') or 0.0)
    
    # 2. Composizione Osservazione e Frame Stacking
    dati_mercato = estrai_prezzi_mercato_veloce()
    feature_esterne = np.array([sentiment, prob_xgb, minuti_news])
    osservazione_corrente = np.concatenate([dati_mercato, feature_esterne])
    
    memoria_osservazioni.append(osservazione_corrente)
    
    if len(memoria_osservazioni) < DIMENSIONE_FRAME:
        time.sleep(1)
        continue
        
    osservazione_impilata = np.concatenate(memoria_osservazioni)
    
    # 3. Inferenza Deterministica PPO
    if modello_ppo:
        azione, _ = modello_ppo.predict(osservazione_impilata, deterministic=True)
    else:
        azione = np.random.randint(0, 3) # 0=Corto, 1=Attesa, 2=Lungo
        
    # 4. Esecuzione Istantanea e Registrazione
    direzioni = {0: "Corto", 1: "Attesa", 2: "Lungo"}
    direzione_scelta = direzioni.get(int(azione), "Attesa")
    
    latenza_ms = (time.time() - inizio_ciclo) * 1000
    
    if direzione_scelta != "Attesa":
        scatola_nera = {
            "sentimento_nlp_italiano": sentiment,
            "probabilita_xgboost": prob_xgb,
            "minuti_ultima_news": minuti_news,
            "latenza_elaborazione_ms": f"{latenza_ms:.2f}"
        }
        audit_db.registra_ordine(
            asset="US100",
            direzione=direzione_scelta,
            esposizione=30000,
            leva=20,
            prezzo_in=18500.0,
            slippage=0.01,
            snapshot_feature=scatola_nera
        )
        print(f"[Sniper] Ordine {direzione_scelta} sparato. Latenza totale: {latenza_ms:.2f}ms")
        
    time.sleep(60)
