import asyncio
import logging
import os
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# Alpaca API keys kept for future order routing
ALPACA_API_KEY = os.getenv("APCA_API_KEY_ID", "")
ALPACA_SECRET_KEY = os.getenv("APCA_API_SECRET_KEY", "")

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "USA Streamer Deactivated (Migrated to Yahoo Protobuf)"}

async def main():
    logger.info("❌ USA Streamer (Alpaca) disattivato. I dati azionari USA sono stati migrati sullo streamer internazionale Yahoo Finance.")
    while True:
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(main())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
