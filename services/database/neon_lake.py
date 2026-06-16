import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class NeonLakeManager:
    def __init__(self):
        self.db_url = os.getenv("NEON_DB_URL")
        self._initialize_db()

    def _get_connection(self):
        if not self.db_url or "inserisci_qui" in self.db_url:
            logger.warning("NEON_DB_URL non configurato o mock. Connessione a DB fallita.")
            return None
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            logger.error(f"Errore di connessione a Neon DB: {e}")
            return None

    def _initialize_db(self):
        conn = self._get_connection()
        if not conn: return
        
        try:
            with conn.cursor() as cur:
                # Tabella per il Dynamic Asset Resolver
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS asset_mapping (
                        ticker_feed VARCHAR(50) PRIMARY KEY,
                        epic_capital VARCHAR(50) NOT NULL,
                        asset_name VARCHAR(150),
                        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # Altre tabelle legacy (trade_logs, genesis, etc.) 
                # rimangono nel db master se necessario.
            conn.commit()
            logger.info("NeonLake: Tabelle inizializzate con successo.")
        except Exception as e:
            logger.error(f"Errore inizializzazione NeonLake: {e}")
        finally:
            conn.close()

    # --- METODI PER IL DYNAMIC ASSET RESOLVER ---
    
    def get_epic_mapping(self, ticker_feed: str):
        """Recupera l'Epic di Capital.com partendo dal Ticker (es. ENEL.MI -> ENEL)"""
        conn = self._get_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT epic_capital, asset_name FROM asset_mapping WHERE ticker_feed = %s", (ticker_feed,))
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Errore lettura asset_mapping per {ticker_feed}: {e}")
            return None
        finally:
            conn.close()

    def save_epic_mapping(self, ticker_feed: str, epic_capital: str, asset_name: str = ""):
        """Salva o aggiorna una corrispondenza tra Ticker Feed e Epic Capital"""
        conn = self._get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO asset_mapping (ticker_feed, epic_capital, asset_name, last_updated)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (ticker_feed) DO UPDATE 
                    SET epic_capital = EXCLUDED.epic_capital,
                        asset_name = EXCLUDED.asset_name,
                        last_updated = CURRENT_TIMESTAMP
                """, (ticker_feed, epic_capital, asset_name))
            conn.commit()
            logger.info(f"NeonLake: Salvato mapping {ticker_feed} -> {epic_capital}")
        except Exception as e:
            logger.error(f"Errore salvataggio asset_mapping: {e}")
        finally:
            conn.close()
