import requests
import pandas as pd
import time
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("CAPITAL_API_KEY")
EMAIL = os.getenv("CAPITAL_EMAIL")
PASSWORD = os.getenv("CAPITAL_PASSWORD")

def login_capital():
    url = "https://demo-api-capital.backend-capital.com/api/v1/session"
    payload = {"identifier": EMAIL, "password": PASSWORD}
    headers = {"X-CAP-API-KEY": API_KEY, "Content-Type": "application/json"}
    res = requests.post(url, json=payload, headers=headers)
    if res.status_code != 200:
        raise Exception(f"Errore Login: {res.text}")
    return res.headers.get("CST"), res.headers.get("X-SECURITY-TOKEN")

def extract_capital_traditional(epic="US100", data_inizio="2024-01-01T00:00:00"):
    if not API_KEY or not EMAIL or not PASSWORD:
        raise ValueError("Credenziali mancanti nel file .env")
    print("🔑 Autenticazione in corso su Capital.com API...")
    cst, x_sec = login_capital()
    headers = {"CST": cst, "X-SECURITY-TOKEN": x_sec, "X-CAP-API-KEY": API_KEY}
    API_URL = "https://demo-api-capital.backend-capital.com"
    
    # FIX 2: Usiamo datetime.now(timezone.utc) per rimuovere il DeprecationWarning
    data_target = datetime.strptime(data_inizio, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    current_end_time = datetime.now(timezone.utc)
    tutti_i_dati = []
    
    print(f"🔄 Inizio estrazione {epic} (M1) a ritroso fino al {data_inizio}...")
    while current_end_time > data_target:
        str_end_time = current_end_time.strftime("%Y-%m-%dT%H:%M:%S")
        url = f"{API_URL}/api/v1/prices/{epic}"
        
        # FIX CRITICO 1: Capital.com usa "MINUTE", non "MINUTE_1"
        params = {"resolution": "MINUTE", "max": 1000, "to": str_end_time}
        
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code != 200:
                print(f"⚠️ Errore API: {res.text}. Ritento...")
                time.sleep(2)
                continue
            data = res.json()
            prices = data.get("prices", [])
            if not prices:
                print("🛑 Nessun altro dato disponibile dal broker.")
                break
            for p in prices:
                tutti_i_dati.append({
                    "Datetime": pd.to_datetime(p["snapshotTime"]),
                    "Open": p["openPrice"]["ask"],
                    "High": p["highPrice"]["ask"],
                    "Low": p["lowPrice"]["ask"],
                    "Close": p["closePrice"]["ask"],
                    "Volume": p["lastTradedVolume"]
                })
            
            oldest_time = pd.to_datetime(prices[0]["snapshotTime"])
            # Gestione sicura della timezone
            if oldest_time.tzinfo is None:
                oldest_time = oldest_time.replace(tzinfo=timezone.utc)
            else:
                oldest_time = oldest_time.astimezone(timezone.utc)
                
            current_end_time = oldest_time - timedelta(seconds=1)
            print(f"Scaricato blocco. Data più antica: {oldest_time.strftime('%Y-%m-%d %H:%M:%S')}. (Tot: {len(tutti_i_dati)})")
            time.sleep(0.5)
        except Exception as e:
            print(f"Errore fatale di rete: {e}")
            break
            
    if not tutti_i_dati: return
    df = pd.DataFrame(tutti_i_dati)
    df.drop_duplicates(subset=['Datetime'], inplace=True)
    df.sort_values('Datetime', inplace=True)
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, "raw_trad_M1.csv")
    df.to_csv(output_file, index=False)
    print(f"✅ Estrazione Tradizionale completata: {len(df)} candele salvate in {output_file}.")

if __name__ == "__main__":
    extract_capital_traditional()
