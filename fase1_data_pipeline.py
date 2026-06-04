import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- SEZIONE 1: CONFIGURAZIONE GOOGLE DRIVE E MASSIVE (POLYGON) ---
# Esegui queste due righe solo se sei su Google Colab
try:
    from google.colab import drive
    drive.mount('/content/drive')
    BASE_DIR = '/content/drive/MyDrive/AI_Trading_Data'
except ImportError:
    # Se lo lanci dal tuo PC locale
    BASE_DIR = './AI_Trading_Data'

os.makedirs(BASE_DIR, exist_ok=True)
print(f"Cartella di salvataggio pronta: {BASE_DIR}")

# La tua chiave Massive / Polygon.io
API_KEY = "xyAaDua5IHP8cGp_jFyWsARblbKXMpPP"
# L'endpoint storico per le candele (aggs) a 1 minuto
BASE_URL = "https://api.polygon.io/v2/aggs/ticker" 

# --- SEZIONE 2: LA LISTA DEGLI ASSET GLOBALI ---
# Aggiungi qui tutti gli asset che desideri. 
# NOTA: Polygon usa prefissi specifici: 'C:' per Forex, 'X:' per Crypto. 
# Le azioni/indici non hanno prefissi (es. SPY, AAPL).
ASSETS = [
    # --- Criptovalute ---
    "X:BTCUSD", "X:ETHUSD", "X:SOLUSD", "X:XRPUSD", "X:DOGEUSD",
    # --- Forex ---
    "C:EURUSD", "C:GBPUSD", "C:USDJPY", "C:AUDUSD",
    # --- Azioni e Indici USA ---
    "SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA", "AMZN", "META"
]

# --- SEZIONE 3: MOTORE DI DOWNLOAD MASSIVO ---
def fetch_data(ticker, start_date, end_date):
    """Scarica un blocco di candele a 1 minuto tramite REST API."""
    # max limit per chiamata è 50.000 candele (circa 34 giorni a 1 minuto in mercati 24/7)
    url = f"{BASE_URL}/{ticker}/range/1/minute/{start_date}/{end_date}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}"
    
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 429:
            print("  [!] Rate Limit toccato. Pausa di 10 secondi...")
            time.sleep(10)
            return fetch_data(ticker, start_date, end_date) # Riprova
            
        data = res.json()
        if data.get("results"):
            df = pd.DataFrame(data["results"])
            # Rinominiamo le colonne criptiche di Polygon
            df['datetime'] = pd.to_datetime(df['t'], unit='ms')
            df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)
            return df[['datetime', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        print(f"  [X] Errore API su {ticker}: {e}")
        
    return pd.DataFrame()

def start_pipeline():
    # Impostiamo il range temporale: 5 Anni fa esatti fino a oggi
    end_date_global = datetime.now()
    start_date_global = end_date_global - timedelta(days=365 * 5)
    
    print(f"Avvio Download Dati a 1 MINUTO da {start_date_global.strftime('%Y-%m-%d')} a {end_date_global.strftime('%Y-%m-%d')}")
    print(f"Totale Asset da processare: {len(ASSETS)}\n")

    for ticker in ASSETS:
        print(f"=====================================")
        print(f"🔽 Inizio download per: {ticker}")
        all_data = []
        
        # Per aggirare il limite di 50k righe per chiamata, spezziamo i 5 anni in blocchi di 25 giorni
        current_start = start_date_global
        while current_start < end_date_global:
            current_end = current_start + timedelta(days=25)
            if current_end > end_date_global:
                current_end = end_date_global
                
            s_str = current_start.strftime("%Y-%m-%d")
            e_str = current_end.strftime("%Y-%m-%d")
            
            print(f"  -> Scarico blocco [{s_str} / {e_str}]...")
            df_chunk = fetch_data(ticker, s_str, e_str)
            
            if not df_chunk.empty:
                all_data.append(df_chunk)
                
            current_start = current_end + timedelta(days=1)
            # Pausa di sicurezza per non martellare il server (0.2s se hai un piano a pagamento, altrimenti alzala a 12s se sei in free)
            time.sleep(0.5) 
            
        if all_data:
            # Uniamo tutti i pezzetti di 25 giorni in un unico enorme DataFrame
            final_df = pd.concat(all_data, ignore_index=True)
            final_df.drop_duplicates(subset=['datetime'], inplace=True)
            final_df.sort_values('datetime', inplace=True)
            
            # Formattiamo il nome del file e salviamo in Parquet ultra-compresso
            safe_name = ticker.replace(":", "_")
            file_path = f"{BASE_DIR}/{safe_name}_1m.parquet"
            
            # PyArrow o FastParquet sono richiesti per salvare in .parquet
            try:
                final_df.to_parquet(file_path, index=False)
                print(f"✅ FATTO! Salvato {ticker}: {len(final_df)} candele in {file_path}")
            except ImportError:
                print("Libreria parquet non trovata. Salvo in CSV come fallback.")
                final_df.to_csv(file_path.replace('.parquet', '.csv'), index=False)
        else:
            print(f"❌ Nessun dato trovato per {ticker}. Forse il ticker è sbagliato?")
            
    print("\n🎉 DATA PIPELINE COMPLETATA! I dati sono pronti nel tuo Google Drive.")

if __name__ == "__main__":
    start_pipeline()
