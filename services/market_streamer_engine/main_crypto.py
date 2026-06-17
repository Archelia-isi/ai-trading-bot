import asyncio
import json
import logging
import os
import aiohttp
import websockets
import redis.asyncio as aioredis

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

import psycopg2

NEON_DATABASE_URL = os.getenv("NEON_DB_URL", "postgresql://neondb_owner:npg_2MxKj4zYebdv@ep-bitter-art-al3j0cxk-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")

async def get_authorized_binance_tickers():
    """Recupera la whitelist dei ticker Crypto dal database Neon"""
    active_symbols = []
    try:
        # Usiamo asyncio.to_thread per non bloccare il loop
        def fetch_db():
            conn = psycopg2.connect(NEON_DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("SELECT ticker_binance FROM capital_market_map WHERE tipo_asset = 'CRIPTO' AND ticker_binance IS NOT NULL;")
                rows = cur.fetchall()
            conn.close()
            return [r[0].lower() for r in rows]
            
        active_symbols = await asyncio.to_thread(fetch_db)
        logger.info(f"Caricati {len(active_symbols)} ticker CRIPTO autorizzati da Neon DB.")
    except Exception as e:
        logger.error(f"Errore recupero simboli da Neon DB: {e}")
    return active_symbols

async def ping_loop(ws):
    """Auto-Heartbeat per prevenire la caduta della connessione (30s)"""
    while True:
        try:
            await asyncio.sleep(30)
            if True:
                # Binance responds to standard websocket pings or we can send application level ping if required
                await ws.ping()
        except Exception as e:
            logger.error(f"Errore Ping Binance: {e}")
            break

async def binance_ws_loop(r: aioredis.Redis):
    uri = "wss://fstream.binance.com/ws"
    retries = 0
    
    while True:
        try:
            symbols = await get_authorized_binance_tickers()
            if not symbols:
                logger.warning("Nessun simbolo trovato, riprovo tra 10s...")
                await asyncio.sleep(10)
                continue
            
            # Limite massimo Binance per streams in una connessione è 1024
            streams = [f"{s}@aggTrade" for s in symbols[:1024]]
            
            logger.info(f"Connessione a Binance Futures per {len(streams)} streams...")
            async with websockets.connect(uri, ping_interval=None) as ws:
                retries = 0
                
                # Auto-Heartbeat Loop
                asyncio.create_task(ping_loop(ws))
                
                # Binance limita a 200 streams per messaggio SUBSCRIBE. Invio a blocchi di 100.
                chunk_size = 100
                for i in range(0, len(streams), chunk_size):
                    chunk = streams[i:i+chunk_size]
                    subscribe_msg = json.dumps({
                        "method": "SUBSCRIBE",
                        "params": chunk,
                        "id": i+1
                    })
                    await ws.send(subscribe_msg)
                    await asyncio.sleep(0.2)
                
                logger.info("✅ Iscrizione a Binance Futures completata a blocchi.")
                
                async for message in ws:
                    data = json.loads(message)
                    if "e" in data and data["e"] == "aggTrade":
                        ticker = data["s"]
                        price = data["p"]
                        volume = data["q"]
                        timestamp = data["T"] # millisecond timestamp
                        
                        payload = {
                            "ticker": ticker,
                            "close": float(price),
                            "volume": float(volume),
                            "exchange": "BINANCE",
                            "timestamp": int(timestamp)
                        }
                        # Push asincrono su Redis per l'Intelligenza Artificiale (Titano Engine V8)
                        await r.publish("market_updates_global", json.dumps(payload))
                        
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione Binance interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await binance_ws_loop(r)

from fastapi import FastAPI
import uvicorn
import os

app = FastAPI()
@app.get("/")
def health_check():
    return {"status": "streamer_crypto online"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(main())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
