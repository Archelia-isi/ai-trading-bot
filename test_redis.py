import asyncio
import aioredis

async def main():
    url = "redis://default:LqEUFVSXRNPMGypkhlSJVJgAKRQFxwIx@yamanote.proxy.rlwy.net:16437"
    try:
        r = aioredis.from_url(url)
        # Check lambda
        val = await r.get("config:xgboost_lambda")
        print(f"config:xgboost_lambda = {val}")
        
        # Check waiting room size
        waiting = await r.hlen("waiting_room_alerts")
        print(f"Waiting Room alerts count: {waiting}")
        
        # Get all waiting room keys
        keys = await r.hkeys("waiting_room_alerts")
        print(f"Waiting Room keys: {keys}")
        
        await r.close()
    except Exception as e:
        print(f"Errore: {e}")

if __name__ == "__main__":
    asyncio.run(main())
