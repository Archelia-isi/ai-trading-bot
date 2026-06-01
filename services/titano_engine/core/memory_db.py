import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger(__name__)

class MemoryDB:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        if not self.db_url:
            logger.warning("DATABASE_URL non configurato. La memoria storica non sarà salvata.")
            
        self.init_db()

    def get_connection(self):
        if not self.db_url:
            return None
        try:
            return psycopg2.connect(self.db_url)
        except Exception as e:
            logger.error(f"Errore connessione DB: {e}")
            return None

    def init_db(self):
        conn = self.get_connection()
        if not conn: return
        
        try:
            with conn.cursor() as cur:
                # Tabella Memoria Decisioni
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS trade_memory (
                        id SERIAL PRIMARY KEY,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        epic VARCHAR(50),
                        action VARCHAR(20),
                        news_sentiment_score FLOAT,
                        xgboost_probability FLOAT,
                        gemini_reasoning TEXT,
                        position_size_pct FLOAT,
                        leverage INT,
                        result_after_24h FLOAT DEFAULT NULL,
                        auditor_grade INT DEFAULT NULL
                    )
                """)
            conn.commit()
            logger.info("Database Memoria Storica inizializzato con successo.")
        except Exception as e:
            logger.error(f"Errore init_db: {e}")
        finally:
            conn.close()

    def log_decision(self, epic, action, sentiment, prob, reasoning, size_pct, leverage):
        conn = self.get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trade_memory (epic, action, news_sentiment_score, xgboost_probability, gemini_reasoning, position_size_pct, leverage)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (epic, action, sentiment, prob, reasoning, size_pct, leverage))
            conn.commit()
        except Exception as e:
            logger.error(f"Errore log_decision: {e}")
        finally:
            conn.close()
