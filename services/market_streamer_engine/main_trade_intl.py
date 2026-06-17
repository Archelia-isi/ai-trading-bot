import asyncio
import json
import logging
import os
import base64
import websockets
import redis.asyncio as aioredis
from typing import List

# Import Protobuf generated schema
from proto import yahoo_finance_pb2

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

import psycopg2

def get_yahoo_epics_from_neon():
    neon_url = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_2MxKj4zYebdv@ep-bitter-art-al3j0cxk-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
    epics = []
    try:
        conn = psycopg2.connect(neon_url)
        cur = conn.cursor()
        cur.execute("SELECT ticker_yahoo FROM capital_market_map WHERE tipo_asset IN ('AZIONE', 'INDICE') AND ticker_yahoo IS NOT NULL")
        for row in cur.fetchall():
            epics.append(row[0])
        cur.close()
        conn.close()
        logger.info(f"Caricati {len(epics)} asset (Azioni/Indici) da Neon DB.")
    except Exception as e:
        logger.error(f"Errore caricamento da Neon DB: {e}")
    return epics

YAHOO_EPICS = get_yahoo_epics_from_neon()

async def ping_loop(ws):
    """Auto-Heartbeat per prevenire la caduta della connessione (30s)"""
    while True:
        try:
            await asyncio.sleep(30)
            if True:
                await ws.ping()
        except Exception as e:
            logger.error(f"Errore Ping: {e}")
            break

async def yahoo_ws_loop(r: aioredis.Redis):
    uri = "wss://streamer.finance.yahoo.com"
    retries = 0
    
    while True:
        try:
            logger.info(f"Connessione a Yahoo Finance WebSocket per {len(YAHOO_EPICS)} asset...")
            async with websockets.connect(uri, ping_interval=None) as ws:
                retries = 0 # reset su connessione stabile
                
                # Auto-Heartbeat Loop
                asyncio.create_task(ping_loop(ws))
                
                subscribe_msg = json.dumps({"subscribe": YAHOO_EPICS})
                await ws.send(subscribe_msg)
                logger.info("✅ Iscrizione a Yahoo completata.")
                
                async for message in ws:
                    try:
                        # Decode base64
                        decoded_bytes = base64.b64decode(message)
                        
                        # Deserialize with Protobuf
                        pricing = yahoo_finance_pb2.TickerPricing()
                        pricing.ParseFromString(decoded_bytes)
                        
                        # Parse Fields
                        ticker = pricing.id
                        price = pricing.price
                        volume = pricing.dayVolume
                        exchange = pricing.exchange
                        timestamp = pricing.time
                        
                        if price > 0:
                            # Standardized JSON
                            payload = {
                                "ticker": ticker,
                                "close": float(price),
                                "volume": int(volume),
                                "exchange": exchange,
                                "timestamp": int(timestamp)
                            }
                            # Push to Redis Memory Buffer
                            await r.publish("market_updates_global", json.dumps(payload))
                            
                    except Exception as parse_error:
                        # Non-fatal error, likely parsing
                        pass
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

from fastapi import FastAPI
import uvicorn
import os

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "INTL Streamer Online"}

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await yahoo_ws_loop(r)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(main())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
