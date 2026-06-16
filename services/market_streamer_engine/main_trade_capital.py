import asyncio
import json
import logging
import os
import websockets
import time
import redis.asyncio as aioredis
from capital_api import CapitalComAPI

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
api = CapitalComAPI()

CAPITAL_MACRO_EPICS = [
    "GOLD", "USOIL", "NATURALGAS", "US500", "US100", "EURUSD", "GBPUSD", "USDJPY"
]

async def ping_loop(ws):
    """Auto-Heartbeat per prevenire la caduta della connessione (30s)"""
    while True:
        try:
            await asyncio.sleep(30)
            if True:
                await ws.ping()
        except Exception as e:
            logger.error(f"Errore Ping Capital: {e}")
            break

async def capital_ws_loop(r: aioredis.Redis):
    if not api.authenticate():
        logger.error("Autenticazione Capital.com fallita.")
        return

    headers = {
        'CST': api.cst_token,
        'X-SECURITY-TOKEN': api.x_security_token,
        'X-CAP-API-KEY': str(api.api_key)
    }
    
    uri = "wss://api-streaming-capital.backend-capital.com/connect"
    retries = 0
    
    while True:
        try:
            logger.info("Connessione a Capital.com WebSocket (Macro/Commodities)...")
            async with websockets.connect(uri, additional_headers=headers, ping_interval=None) as ws:
                retries = 0
                
                # Auto-Heartbeat Loop
                asyncio.create_task(ping_loop(ws))
                
                subscribe_msg = {
                    "destination": "marketdata.subscribe",
                    "payload": { "epics": CAPITAL_MACRO_EPICS }
                }
                await ws.send(json.dumps(subscribe_msg))
                logger.info("✅ Iscrizione a Capital.com completata.")
                
                async for message in ws:
                    data = json.loads(message)
                    if "payload" in data:
                        tick = data["payload"]
                        epic = tick.get("epic")
                        bid = tick.get("bid")
                        ask = tick.get("ofr")
                        # Capital.com timestamp uses millisecond timestamp? Usually not provided directly in all ticks, so use local time or tick time
                        timestamp = tick.get("timestamp", int(time.time() * 1000))
                        
                        if epic and bid and ask:
                            mid_price = (bid + ask) / 2
                            payload = {
                                "ticker": epic,
                                "close": float(mid_price),
                                "volume": 1, # Fake volume for forex/indices
                                "exchange": "CAPITAL",
                                "timestamp": int(timestamp)
                            }
                            await r.publish("market_updates_global", json.dumps(payload))
                            
        except Exception as e:
            wait_time = min(0.05 * (2 ** retries), 5.0)
            logger.error(f"❌ Connessione Capital interrotta: {e}. Riconnessione in {wait_time:.2f}s...")
            await asyncio.sleep(wait_time)
            retries += 1

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    await capital_ws_loop(r)

if __name__ == "__main__":
    asyncio.run(main())
