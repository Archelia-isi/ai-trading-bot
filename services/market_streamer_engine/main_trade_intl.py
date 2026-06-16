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

# Lista di base delle azioni Europee e Asiatiche
EUROPEAN_STOCKS = [
    "MC.PA", "OR.PA", "TTE.PA", "SU.PA", "ASML.AS", "SAP.DE", "SIE.DE", 
    "VOW3.DE", "ALV.DE", "ENEL.MI", "RACE.MI", "UCG.MI", "ISP.MI", "ENI.MI",
    "IBE.MC", "SAN.MC", "ITX.MC", "HSBA.L", "SHEL.L", "AZN.L", "NVO", "NVS"
]

ASIAN_STOCKS = [
    "7203.T", "6758.T", "7267.T", "TSM", "BABA", "JD", "BIDU", 
    "INFY", "HDB", "TTM", "0700.HK"
]

# Ticker USA puri senza suffisso (Decodificati come USA)
USA_STOCKS = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "BRK.B", "LLY", "AVGO", "V",
    "JPM", "TSLA", "WMT", "UNH", "MA", "XOM", "JNJ", "PG", "HD", "COST",
    "ORCL", "MRK", "ABBV", "CVX", "CRM", "BAC", "NFLX", "KO", "PEP", "TMO"
]

YAHOO_EPICS = EUROPEAN_STOCKS + ASIAN_STOCKS + USA_STOCKS

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
