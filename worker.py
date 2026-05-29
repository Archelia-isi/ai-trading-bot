import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def portfolio_manager_loop():
    logger.warning("VECCHIO WORKER (SCAGLIONI E GEMINI) DISATTIVATO DEFINITIVAMENTE.")
    logger.warning("Siamo in attesa del nuovo Monitor Engine Autonomo (Fase 3).")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(portfolio_manager_loop())
