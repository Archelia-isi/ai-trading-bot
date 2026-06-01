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
                    
                    CREATE TABLE IF NOT EXISTS trade_genesis (
                        id SERIAL PRIMARY KEY,
                        epic VARCHAR(50) NOT NULL,
                        direction VARCHAR(10) NOT NULL,
                        opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        closed_at TIMESTAMP,
                        news_title TEXT,
                        xgboost_prob FLOAT,
                        gemini_reasoning TEXT,
                        executed_size FLOAT,
                        leverage INT,
                        outcome_pnl FLOAT,
                        is_evaluated BOOLEAN DEFAULT FALSE
                    );
                    
                    CREATE TABLE IF NOT EXISTS ai_protocols (
                        id SERIAL PRIMARY KEY,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        epic VARCHAR(50),
                        protocol_text TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE
                    );
                    
                    CREATE TABLE IF NOT EXISTS market_candles (
                        epic VARCHAR(50) NOT NULL,
                        timestamp BIGINT NOT NULL,
                        open FLOAT,
                        high FLOAT,
                        low FLOAT,
                        close FLOAT,
                        volume FLOAT,
                        PRIMARY KEY (epic, timestamp)
                    );
                """)
            conn.commit()
            logger.info("Database inizializzato (tabelle verificate).")
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

    def truncate_logs(self):
        """Svuota completamente la tabella trade_logs (utile per pulizia test)."""
        conn = self._get_connection()
        if not conn:
            return False
            
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE trade_logs RESTART IDENTITY;")
            conn.commit()
            logger.info("Tabella trade_logs svuotata con successo.")
            return True
        except Exception as e:
            logger.error(f"Errore durante lo svuotamento del DB: {e}")
            return False
        finally:
            conn.close()

    # --- SUPERVISOR METHODS ---
    
    def log_trade_genesis(self, epic: str, direction: str, news_title: str, xgboost_prob: float, gemini_reasoning: str, executed_size: float, leverage: int):
        conn = self._get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trade_genesis (epic, direction, news_title, xgboost_prob, gemini_reasoning, executed_size, leverage)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (epic, direction, news_title, xgboost_prob, gemini_reasoning, executed_size, leverage))
            conn.commit()
            logger.info(f"Genesi del trade {epic} salvata nel DB.")
        except Exception as e:
            logger.error(f"Errore salvataggio genesis: {e}")
        finally:
            conn.close()

    def get_unevaluated_trades(self):
        conn = self._get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM trade_genesis WHERE is_evaluated = FALSE")
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Errore recupero trade non valutati: {e}")
            return []
        finally:
            conn.close()

    def get_recently_evaluated_trades(self, limit=100):
        """Recupera i trade chiusi con PnL per il retrain (Experience Replay)."""
        conn = self._get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM trade_genesis WHERE is_evaluated = TRUE ORDER BY closed_at DESC LIMIT %s", (limit,))
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Errore recupero trade valutati per Online Learning: {e}")
            return []
        finally:
            conn.close()

    def mark_trade_evaluated(self, trade_id: int, pnl: float):
        conn = self._get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE trade_genesis 
                    SET is_evaluated = TRUE, outcome_pnl = %s, closed_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (pnl, trade_id))
            conn.commit()
        except Exception as e:
            logger.error(f"Errore aggiornamento trade valutato: {e}")
        finally:
            conn.close()

    def save_ai_protocol(self, protocol_text: str, epic: str = None):
        conn = self._get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ai_protocols (epic, protocol_text)
                    VALUES (%s, %s)
                """, (epic, protocol_text))
            conn.commit()
            logger.info("Nuovo Protocollo AI salvato nel DB!")
        except Exception as e:
            logger.error(f"Errore salvataggio protocollo: {e}")
        finally:
            conn.close()

    def get_active_protocols(self):
        conn = self._get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM ai_protocols WHERE is_active = TRUE ORDER BY created_at DESC")
                return cur.fetchall()
        except Exception as e:
            logger.error(f"Errore recupero protocolli: {e}")
            return []
        finally:
            conn.close()

    def save_candles(self, epic: str, candles: list):
        """Salva in bulk le candele storiche ignorando i duplicati."""
        conn = self._get_connection()
        if not conn or not candles: return
        try:
            with conn.cursor() as cur:
                args = []
                for c in candles:
                    args.append((
                        epic, 
                        c['timestamp'], 
                        c['openPrice']['bid'], 
                        c['highPrice']['bid'], 
                        c['lowPrice']['bid'], 
                        c['closePrice']['bid'], 
                        c['lastTradedVolume']
                    ))
                
                query = """
                    INSERT INTO market_candles (epic, timestamp, open, high, low, close, volume)
                    VALUES %s
                    ON CONFLICT (epic, timestamp) DO NOTHING
                """
                from psycopg2.extras import execute_values
                execute_values(cur, query, args)
            conn.commit()
        except Exception as e:
            logger.error(f"Errore salvataggio candele per {epic}: {e}")
        finally:
            conn.close()

    def get_candles(self, epic: str, limit: int = 1000) -> list:
        """Recupera le ultime N candele dal Data Lake per l'epic, ordinate temporalmente dal più vecchio al più recente."""
        conn = self._get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM market_candles 
                    WHERE epic = %s 
                    ORDER BY timestamp DESC 
                    LIMIT %s
                """, (epic, limit))
                rows = cur.fetchall()
                # Reverse to get chronological order (oldest to newest)
                rows = list(reversed(rows))
                
                result = []
                for row in rows:
                    result.append({
                        "timestamp": row['timestamp'],
                        "openPrice": {"bid": row['open']},
                        "highPrice": {"bid": row['high']},
                        "lowPrice": {"bid": row['low']},
                        "closePrice": {"bid": row['close']},
                        "lastTradedVolume": row['volume']
                    })
                return result
        except Exception as e:
            logger.error(f"Errore lettura candele per {epic}: {e}")
            return []
        finally:
            conn.close()
