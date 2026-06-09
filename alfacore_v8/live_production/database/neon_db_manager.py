import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()

class TradeAudit(Base):
    __tablename__ = 'trade_audit'
    id = Column(Integer, primary_key=True)
    timestamp_utc = Column(DateTime, default=datetime.utcnow)
    action = Column(String(10)) # LONG, SHORT, FLAT
    obs_snapshot = Column(String) # JSON
    entry_price = Column(Float)
    slippage_paid = Column(Float)
    simulated_equity = Column(Float)

class NeonDBManager:
    def __init__(self):
        db_url = os.getenv("NEON_DB_URL")
        if not db_url:
            print("⚠️ NEON_DB_URL non impostato. Avvio in modalità SQLite locale.")
            db_url = "sqlite:///local_audit.db"
            
        self.engine = create_engine(db_url, pool_pre_ping=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        
    def log_trade_action(self, action, obs_snapshot, entry_price, slippage, equity):
        session = self.Session()
        try:
            trade = TradeAudit(
                action=action,
                obs_snapshot=json.dumps(obs_snapshot),
                entry_price=entry_price,
                slippage_paid=slippage,
                simulated_equity=equity
            )
            session.add(trade)
            session.commit()
            print(f"📒 Audit Log Salvato: Azione {action} su {db_url.split('@')[-1] if '@' in db_url else 'SQLite'}")
        except Exception as e:
            session.rollback()
            print(f"Errore DB Audit: {e}")
        finally:
            session.close()
