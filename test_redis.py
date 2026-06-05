import asyncio
import aioredis
import os
import json

async def test():
    r = await aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    await r.publish("system_commands", json.dumps({"command": "force_gym"}))
    print("sent!")
    await r.close()

asyncio.run(test())
