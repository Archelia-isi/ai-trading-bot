import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_url = os.getenv("NEON_DB_URL")
        self._initialize_db()

    def _get_connection(self):
        if not self.db_url or "inserisci_qui" in self.db_url:
            logger.warning("NEON_DB_URL non configurato correttamente. Salvataggio su DB ignorato.")
            return None
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            logger.error(f"Errore di connessione a Neon DB: {e}")
            return None

    def _initialize_db(self):
        """Crea la tabella trade_logs se non esiste."""
        conn = self._get_connection()
        if not conn:
            return
        
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trade_logs (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        asset VARCHAR(50) NOT NULL,
                        action VARCHAR(10) NOT NULL,
                        score INTEGER,
                        risk_profile VARCHAR(50),
                        size FLOAT,
                        price FLOAT,
                        status VARCHAR(20)
                    );
                """)
            conn.commit()
            logger.info("Database inizializzato (tabella trade_logs verificata).")
        except Exception as e:
            logger.error(f"Errore durante l'inizializzazione del DB: {e}")
        finally:
            conn.close()

    def log_trade(self, asset: str, action: str, score: int, risk_profile: str, size: float, price: float, status: str = "OPEN"):
        """Salva un'operazione nel database serverless."""
        conn = self._get_connection()
        if not conn:
            logger.info(f"[SIMULATO SU CONSOLE] Log Trade: {action} su {asset} a {price} (Score {score})")
            return
            
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trade_logs (asset, action, score, risk_profile, size, price, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (asset, action, score, risk_profile, size, price, status))
            conn.commit()
            logger.info(f"Log salvato permanentemente in Neon DB: {action} {asset} a {price}")
        except Exception as e:
            logger.error(f"Errore durante l'inserimento nel DB: {e}")
        finally:
            conn.close()
            
    def get_recent_logs(self, limit=10):
        """Recupera gli ultimi trade logs formattati per la UI."""
        conn = self._get_connection()
        if not conn:
            return []
            
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM trade_logs ORDER BY timestamp DESC LIMIT %s", (limit,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Errore nella lettura dei log dal DB: {e}")
            return []
        finally:
            conn.close()
