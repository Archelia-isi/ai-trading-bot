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

async def get_active_binance_futures():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    active_symbols = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    symbols = data.get("symbols", [])
                    for s in symbols:
                        if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
                            active_symbols.append(s.get("symbol").lower())
                else:
                    logger.error(f"Errore API Binance: {response.status} - {await response.text()}")
    except Exception as e:
        logger.error(f"Errore recupero simboli Binance: {e}")
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
            symbols = await get_active_binance_futures()
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
                
                # Subscribe
                subscribe_msg = json.dumps({
                    "method": "SUBSCRIBE",
                    "params": streams,
                    "id": 1
                })
                await ws.send(subscribe_msg)
                logger.info("✅ Iscrizione a Binance Futures completata.")
                
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
                        # Push to Redis Memory Buffer
                        await r.publish("market_updates_global", json.dumps(payload))
                        
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione Binance interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await binance_ws_loop(r)

if __name__ == "__main__":
    asyncio.run(main())
