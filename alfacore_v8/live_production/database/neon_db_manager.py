import os
import json
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()

class RegistroOperazioni(Base):
    __tablename__ = 'registro_operazioni'
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp_esecuzione = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    asset = Column(String(50))
    direzione = Column(String(20))
    esposizione_nominale = Column(Float)
    leva_finanziaria = Column(Float)
    prezzo_ingresso = Column(Float)
    slippage_stimato = Column(Float)
    scatola_nera_json = Column(Text)  # Snapshot delle feature per analisi quantitativa

class GestoreNeonDB:
    def __init__(self):
        db_url = os.getenv("NEON_DB_URL")
        if not db_url:
            print("Avviso: NEON_DB_URL mancante. Verrà utilizzato SQLite locale per l'Audit.")
            db_url = "sqlite:///audit_locale.db"
            self.motore = create_engine(db_url)
        else:
            # pool_pre_ping previene le cadute di connessione tipiche del Serverless PostgreSQL
            self.motore = create_engine(db_url, pool_pre_ping=True)
            
        Base.metadata.create_all(self.motore)
        self.Sessione = sessionmaker(bind=self.motore)
        
    def registra_ordine(self, asset, direzione, esposizione, leva, prezzo_in, slippage, snapshot_feature):
        sessione = self.Sessione()
        try:
            nuova_operazione = RegistroOperazioni(
                asset=asset,
                direzione=direzione,
                esposizione_nominale=esposizione,
                leva_finanziaria=leva,
                prezzo_ingresso=prezzo_in,
                slippage_stimato=slippage,
                scatola_nera_json=json.dumps(snapshot_feature)
            )
            sessione.add(nuova_operazione)
            sessione.commit()
            print(f"Audit completato: Operazione su {asset} salvata nel ledger permanente.")
        except Exception as e:
            sessione.rollback()
            print(f"Errore critico durante la scrittura dell'audit: {e}")
        finally:
            sessione.close()
