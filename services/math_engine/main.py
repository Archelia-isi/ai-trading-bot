from fastapi import FastAPI
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Math Engine (Disattivato)")

@app.on_event("startup")
async def startup_event():
    logger.warning("VECCHIO MATH ENGINE (XGBOOST E CACCIATORE) DISATTIVATO DEFINITIVAMENTE.")
    logger.warning("Nessun segnale verrà inviato all'Audit. In attesa del nuovo Transformer.")

@app.get("/")
def health_check():
    return {"status": "offline", "message": "In attesa del nuovo Monitor Engine"}
