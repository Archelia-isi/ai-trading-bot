import asyncio
import json
import logging
import os
import websockets
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ALPACA_API_KEY = os.getenv("APCA_API_KEY_ID", "your_alpaca_key")
ALPACA_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY", "your_alpaca_secret")

async def ping_loop(ws):
    """Auto-Heartbeat per prevenire la caduta della connessione (30s)"""
    while True:
        try:
            await asyncio.sleep(30)
            if True:
                # Alpaca IEX websocket responds to standard WebSocket pings
                await ws.ping()
        except Exception as e:
            logger.error(f"Errore Ping Alpaca: {e}")
            break

async def alpaca_ws_loop(r: aioredis.Redis):
    uri = "wss://stream.data.alpaca.markets/v2/iex"
    retries = 0
    
    while True:
        try:
            logger.info("Connessione ad Alpaca Markets WebSocket (USA Firehose)...")
            async with websockets.connect(uri, ping_interval=None) as ws:
                retries = 0
                
                # Auto-Heartbeat Loop
                asyncio.create_task(ping_loop(ws))
                
                # Authenticate
                auth_message = json.dumps({
                    "action": "auth",
                    "key": ALPACA_API_KEY,
                    "secret": ALPACA_SECRET_KEY
                })
                await ws.send(auth_message)
                
                auth_response = await ws.recv()
                logger.info(f"Alpaca Auth Response: {auth_response}")
                
                # Subscribe to ALL trades
                subscribe_msg = json.dumps({
                    "action": "subscribe",
                    "trades": ["*"]
                })
                await ws.send(subscribe_msg)
                logger.info("✅ Iscrizione ad Alpaca Firehose completata.")
                
                async for message in ws:
                    data = json.loads(message)
                    for event in data:
                        # Evento T = Trade
                        if event.get('T') == 't':
                            ticker = event.get('S')
                            price = event.get('p')
                            volume = event.get('s')
                            timestamp = event.get('t') # nanoseconds potentially? typically RFC3339 or epoch
                            # Alpaca 't' is RFC-3339 formatted string like "2021-02-22T15:22:00.023456789Z"
                            # For simplicity we might just pass it as string or convert. We'll pass it to redis.
                            
                            payload = {
                                "ticker": ticker,
                                "close": float(price),
                                "volume": int(volume),
                                "exchange": "USA",
                                "timestamp": str(timestamp)
                            }
                            # Push to Redis Memory Buffer
                            await r.publish("market_updates_global", json.dumps(payload))
                            
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione Alpaca interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await alpaca_ws_loop(r)

if __name__ == "__main__":
    asyncio.run(main())
