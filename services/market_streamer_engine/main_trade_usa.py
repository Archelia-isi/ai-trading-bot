import asyncio
import json
import logging
import os
import redis.asyncio as aioredis
from dotenv import load_dotenv
from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed
from fastapi import FastAPI
import uvicorn

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ALPACA_API_KEY = os.getenv("APCA_API_KEY_ID", "PK36Z7BYC46PJXLA5YWBA22QNV")
ALPACA_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY", "3gN1PUs2YSrdHFFfVs7ZQmvLT8h2RdtLJ3UyU3fSjvAL")

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "USA Streamer Online (alpaca-py)"}

async def alpaca_ws_loop(r: aioredis.Redis):
    retries = 0
    while True:
        try:
            logger.info("Connessione ad Alpaca Markets WebSocket (USA Firehose con alpaca-py)...")
            
            stream = StockDataStream(
                ALPACA_API_KEY, 
                ALPACA_SECRET_KEY, 
                feed=DataFeed.IEX # Free tier requires IEX
            )
            
            async def trade_callback(t):
                payload = {
                    "ticker": t.symbol,
                    "close": float(t.price),
                    "volume": int(t.size),
                    "exchange": "USA",
                    "timestamp": str(t.timestamp)
                }
                # Publish asynchronously using a fire-and-forget task to avoid blocking the callback
                asyncio.create_task(r.publish("market_updates_global", json.dumps(payload)))

            logger.info("✅ Sottoscrizione a tutte le azioni (IEX Free Tier supportato)...")
            stream.subscribe_trades(trade_callback, "*")
            
            logger.info("✅ Streamer avviato in ascolto su Alpaca.")
            await stream._run_forever()
            
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione Alpaca interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await alpaca_ws_loop(r)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(main())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
