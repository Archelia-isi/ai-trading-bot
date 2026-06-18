import os
import sys
import time
import random
import logging
import requests
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Configurazione Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("scraper")

NEON_DATABASE_URL = os.getenv("NEON_DB_URL", "postgresql://neondb_owner:npg_2MxKj4zYebdv@ep-bitter-art-al3j0cxk-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
CAPITAL_API_URL = os.getenv("CAPITAL_API_URL", "https://api-capital.backend-capital.com/api/v1")
API_KEY = os.getenv("CAPITAL_API_KEY", "JoAgiPRKn7ZPpyuc")
EMAIL = os.getenv("CAPITAL_EMAIL", "salvatore@immobiliareizzo.com")
PASSWORD = os.getenv("CAPITAL_PASSWORD", "Salvatore1!")

# Percorsi Locali (Railway Volume)
DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "./data/historical_1m")
os.makedirs(DATA_DIR, exist_ok=True)

class HistoricalScraper:
    def __init__(self):
        self.headers = {
            "X-CAP-API-KEY": API_KEY,
            "Content-Type": "application/json"
        }
        self.auth_capital()
        self.init_db()

    def auth_capital(self):
        logger.info("🔐 Autenticazione a Capital.com...")
        resp = requests.post(f"{CAPITAL_API_URL}/session", json={"identifier": EMAIL, "password": PASSWORD, "encryptedPassword": False}, headers=self.headers)
        if resp.status_code == 200:
            self.headers["CST"] = resp.headers.get("CST")
            self.headers["X-SECURITY-TOKEN"] = resp.headers.get("X-SECURITY-TOKEN")
            logger.info("✅ Autenticazione Capital.com riuscita")
        else:
            logger.error(f"❌ Auth fallita: {resp.status_code} - {resp.text}")

    def api_sleep(self):
        delay = random.uniform(1.5, 2.5)
        time.sleep(delay)

    def handle_rate_limit(self):
        logger.warning("🚨 Rate limit toccato o ban API! Pausa di 5 minuti...")
        time.sleep(300)
        self.auth_capital()

    def init_db(self):
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scraper_checkpoint (
                epic VARCHAR(100) PRIMARY KEY,
                min_timestamp TIMESTAMP WITH TIME ZONE,
                max_timestamp TIMESTAMP WITH TIME ZONE,
                last_sync TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ Tabella scraper_checkpoint inizializzata su Neon DB.")

    def get_target_epics(self):
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT codice_capital_epic FROM capital_market_map;")
        epics = [row[0] for row in cur.fetchall()]
        cur.close()
        conn.close()
        return epics

    def get_checkpoint(self, epic):
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT min_timestamp, max_timestamp FROM scraper_checkpoint WHERE epic = %s;", (epic,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return row[0], row[1]
        return None, None

    def update_checkpoint(self, epic, min_ts, max_ts):
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scraper_checkpoint (epic, min_timestamp, max_timestamp, last_sync)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (epic) DO UPDATE SET
                min_timestamp = EXCLUDED.min_timestamp,
                max_timestamp = EXCLUDED.max_timestamp,
                last_sync = CURRENT_TIMESTAMP;
        """, (epic, min_ts, max_ts))
        conn.commit()
        cur.close()
        conn.close()

    def fetch_prices(self, epic, from_date, to_date):
        url = f"{CAPITAL_API_URL}/prices/{epic}?resolution=MINUTE&from={from_date.strftime('%Y-%m-%dT%H:%M:%S')}&to={to_date.strftime('%Y-%m-%dT%H:%M:%S')}"
        res = requests.get(url, headers=self.headers)
        if res.status_code in [400, 401, 403, 429] or "error.null.client.token" in res.text:
            logger.warning(f"Token scaduto o limit raggiunto ({res.status_code}). Riautenticazione in corso...")
            self.handle_rate_limit()
            return self.fetch_prices(epic, from_date, to_date)
        if res.status_code != 200:
            logger.error(f"Errore {res.status_code} su {epic}: {res.text}")
            return None
        data = res.json()
        if not data.get("prices"): return None
        
        records = []
        for p in data["prices"]:
            dt = datetime.strptime(p["snapshotTimeUTC"], "%Y-%m-%dT%H:%M:%S")
            records.append({
                "datetime": dt,
                "open": p["openPrice"]["bid"],
                "high": p["highPrice"]["bid"],
                "low": p["lowPrice"]["bid"],
                "close": p["closePrice"]["bid"],
                "volume": p["lastTradedVolume"]
            })
        return pd.DataFrame(records)

    def merge_and_save_parquet(self, epic, df_new):
        filepath = os.path.join(DATA_DIR, f"{epic}.parquet")
        if os.path.exists(filepath):
            df_old = pd.read_parquet(filepath)
            df_merged = pd.concat([df_old, df_new])
            df_merged.drop_duplicates(subset=["datetime"], inplace=True)
            df_merged.sort_values(by="datetime", inplace=True)
        else:
            df_merged = df_new.sort_values(by="datetime")
            
        df_merged.to_parquet(filepath, index=False)
        return df_merged

    def sync_backward(self, epic, min_ts):
        target_years = 5
        target_date = datetime.utcnow() - timedelta(days=365*target_years)
        if min_ts and min_ts.replace(tzinfo=None) <= target_date:
            return min_ts # Già raggiunto l'obiettivo retrospettivo
            
        current_to = min_ts.replace(tzinfo=None) if min_ts else datetime.utcnow()
        # Chiediamo un blocco di 16 ore (960 minuti < 1000 limit di Capital.com)
        current_from = current_to - timedelta(hours=16) 
        
        logger.info(f"[{epic}] BACKWARD: {current_from.strftime('%Y-%m-%d %H:%M')} -> {current_to.strftime('%H:%M')}")
        df = self.fetch_prices(epic, current_from, current_to)
        self.api_sleep()
        
        if df is not None and not df.empty:
            actual_min = df["datetime"].min()
            self.merge_and_save_parquet(epic, df)
            return actual_min
        else:
            # Mercato chiuso o gap temporale, abbassiamo artificialmente il min_ts per saltare il buco
            return current_from

    def sync_forward(self, epic, max_ts):
        if not max_ts: return None
        
        now = datetime.utcnow()
        max_ts_naive = max_ts.replace(tzinfo=None)
        if max_ts_naive >= now - timedelta(minutes=5):
            return max_ts # Già sincronizzato al momento attuale
            
        current_from = max_ts_naive
        # Massimo blocco richiedibile: 16 ore
        current_to = min(now, current_from + timedelta(hours=16))
        
        logger.info(f"[{epic}] FORWARD: {current_from.strftime('%Y-%m-%d %H:%M')} -> {current_to.strftime('%H:%M')}")
        df = self.fetch_prices(epic, current_from, current_to)
        self.api_sleep()
        
        if df is not None and not df.empty:
            actual_max = df["datetime"].max()
            self.merge_and_save_parquet(epic, df)
            return actual_max
        else:
            # Scaliamo in avanti il checkpoint per attraversare le ore di chiusura
            return current_to

    def upload_to_drive(self, epic):
        try:
            creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            if not creds_json:
                logger.debug("Nessuna credenziale Google trovata in GOOGLE_APPLICATION_CREDENTIALS_JSON. Backup saltato.")
                return
            
            try:
                creds_dict = json.loads(creds_json)
            except json.JSONDecodeError:
                import ast
                creds_dict = ast.literal_eval(creds_json)
                
            credentials = service_account.Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
            service = build('drive', 'v3', credentials=credentials)
            
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            if not folder_id:
                logger.error("Manca la variabile GOOGLE_DRIVE_FOLDER_ID. Impossibile caricare su Drive.")
                return
            
            local_path = os.path.join(DATA_DIR, f"{epic}.parquet")
            if not os.path.exists(local_path):
                return
                
            file_name = f"{epic}.parquet"
            # Cerchiamo se il file esiste già per poterlo sovrascrivere
            query = f"name='{file_name}' and '{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, spaces='drive', fields='files(id, name)', supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            items = results.get('files', [])
            
            media = MediaFileUpload(local_path, mimetype='application/octet-stream', resumable=True)
            if not items:
                # Crea nuovo file
                file_metadata = {'name': file_name, 'parents': [folder_id]}
                service.files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
                logger.info(f"☁️ Caricato nuovo file su Drive Condiviso per {epic}")
            else:
                # Aggiorna file esistente (Sovrascrittura)
                file_id = items[0]['id']
                service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
                logger.info(f"☁️ Aggiornato (sovrascritto) file su Drive Condiviso per {epic}")
                
        except Exception as e:
            logger.error(f"Errore upload su Drive per {epic}: {e}")

    def run_daemon(self):
        logger.info("🤖 Avvio Historical Data Scraper Daemon...")
        while True:
            epics = self.get_target_epics()
            logger.info(f"🔄 Inizio scansione globale su {len(epics)} asset.")
            
            for epic in epics:
                min_ts, max_ts = self.get_checkpoint(epic)
                
                # FASE 1: Download Retrospettivo
                new_min_ts = self.sync_backward(epic, min_ts)
                
                # FASE 2: Aggiornamento in Avanti
                new_max_ts = self.sync_forward(epic, max_ts if max_ts else new_min_ts)
                
                # Update Neon DB
                if new_min_ts or new_max_ts:
                    self.update_checkpoint(epic, new_min_ts, new_max_ts)
                    # Sync Cloud
                    self.upload_to_drive(epic)
                
            logger.info("💤 Ciclo globale completato. Pausa di cortesia di 15 minuti...")
            time.sleep(900)

if __name__ == "__main__":
    scraper = HistoricalScraper()
    scraper.run_daemon()
