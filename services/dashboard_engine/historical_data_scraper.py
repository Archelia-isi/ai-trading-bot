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

    def update_min_checkpoint(self, epic, min_ts):
        if not min_ts: return
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scraper_checkpoint (epic, min_timestamp, last_sync)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (epic) DO UPDATE SET
                min_timestamp = EXCLUDED.min_timestamp,
                last_sync = CURRENT_TIMESTAMP;
        """, (epic, min_ts))
        conn.commit()
        cur.close()
        conn.close()

    def update_max_checkpoint(self, epic, max_ts):
        if not max_ts: return
        conn = psycopg2.connect(NEON_DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scraper_checkpoint (epic, max_timestamp, last_sync)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (epic) DO UPDATE SET
                max_timestamp = EXCLUDED.max_timestamp,
                last_sync = CURRENT_TIMESTAMP;
        """, (epic, max_ts))
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

    def sync_backward_full(self, epic, min_ts):
        target_years = 5
        target_date = datetime.utcnow() - timedelta(days=365*target_years)
        
        current_min_ts = min_ts
        empty_fetches_in_a_row = 0
        blocks = 0
        
        if current_min_ts and current_min_ts.replace(tzinfo=None) <= target_date:
            return current_min_ts
            
        logger.info(f"[{epic}] Avvio Deep Sync Backward fino a 5 anni...")
        while True:
            if current_min_ts and current_min_ts.replace(tzinfo=None) <= target_date:
                logger.info(f"[{epic}] Obiettivo 5 anni raggiunto!")
                break
                
            current_to = current_min_ts.replace(tzinfo=None) if current_min_ts else datetime.utcnow()
            current_from = current_to - timedelta(hours=16)
            
            logger.info(f"[{epic}] BACKWARD DEEP: {current_from.strftime('%Y-%m-%d %H:%M')} -> {current_to.strftime('%H:%M')}")
            df = self.fetch_prices(epic, current_from, current_to)
            self.api_sleep()
            
            if df is not None and not df.empty:
                current_min_ts = df["datetime"].min()
                self.merge_and_save_parquet(epic, df)
                empty_fetches_in_a_row = 0
            else:
                current_min_ts = current_from
                empty_fetches_in_a_row += 1
                
            blocks += 1
            if blocks % 20 == 0:
                logger.info(f"[{epic}] Salvataggio intermedio checkpoint e drive (blocco {blocks})")
                self.update_min_checkpoint(epic, current_min_ts)
                self.upload_to_drive(epic)
                
            if empty_fetches_in_a_row >= 21: # 14 giorni senza dati -> fine storico
                logger.info(f"[{epic}] Storico esaurito per questo asset (14 giorni senza dati).")
                current_min_ts = target_date
                break
                
        # Salvataggio finale
        self.update_min_checkpoint(epic, current_min_ts)
        self.upload_to_drive(epic)
        return current_min_ts

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
            token_json = os.getenv("GOOGLE_OAUTH_TOKEN_JSON")
            if not token_json:
                logger.debug("Nessun token OAuth in GOOGLE_OAUTH_TOKEN_JSON. Backup saltato.")
                return
            
            # Parsing flessibile in caso di virgolette singole o malformazioni di Railway
            try:
                token_dict = json.loads(token_json)
            except json.JSONDecodeError:
                import ast
                token_dict = ast.literal_eval(token_json)
                
            from google.oauth2.credentials import Credentials
            credentials = Credentials.from_authorized_user_info(token_dict, scopes=['https://www.googleapis.com/auth/drive'])
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
        target_years = 5
        
        while True:
            epics = self.get_target_epics()
            logger.info(f"🔄 Inizio scansione globale su {len(epics)} asset.")
            
            # FASE 1: Sync FORWARD per tutti gli asset
            logger.info("⏩ Inizio FASE FORWARD globale...")
            for epic in epics:
                min_ts, max_ts = self.get_checkpoint(epic)
                # Fallback: se non c'è max_ts, si parte da 1 giorno fa per il forward veloce
                new_max_ts = self.sync_forward(epic, max_ts if max_ts else (datetime.utcnow() - timedelta(days=1)))
                
                if new_max_ts and new_max_ts != max_ts:
                    self.update_max_checkpoint(epic, new_max_ts)
                    self.upload_to_drive(epic)
            
            # FASE 2: Sync BACKWARD profondo per un sottoinsieme di asset
            logger.info("⏪ Inizio FASE BACKWARD (Deep Sync per 5 asset)...")
            target_date = datetime.utcnow() - timedelta(days=365*target_years)
            
            pending_epics = []
            for epic in epics:
                min_ts, _ = self.get_checkpoint(epic)
                if not min_ts or min_ts.replace(tzinfo=None) > target_date:
                    pending_epics.append((epic, min_ts))
                    
            logger.info(f"Asset che necessitano ancora di storico: {len(pending_epics)}")
            
            for epic, min_ts in pending_epics[:5]:
                self.sync_backward_full(epic, min_ts)
                
            logger.info("💤 Ciclo globale completato. Pausa di cortesia di 15 minuti...")
            time.sleep(900)

if __name__ == "__main__":
    scraper = HistoricalScraper()
    scraper.run_daemon()
