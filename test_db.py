import asyncio
import os
import sys
# Add current dir to path to import services
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from services.supervisor_engine.core.database import DatabaseManager

db = DatabaseManager()
logs = db.get_recent_logs(limit=10)
print("--- RECENT LOGS ---")
for l in logs:
    print(f"[{l['timestamp']}] {l['action']} {l['asset']} @ {l['price']} | Status: {l['status']}")

conn = db._get_connection()
if conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM trade_genesis WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 5")
        closed = cur.fetchall()
        print("\n--- RECENTLY CLOSED GENESIS TRADES ---")
        for c in closed:
            print(c)
    conn.close()
else:
    print("Could not connect to database")
