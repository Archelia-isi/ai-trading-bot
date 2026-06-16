import asyncio
from services.audit_engine.capital_api import CapitalComAPI

async def main():
    api = CapitalComAPI()
    print("Authenticating...")
    success = api.authenticate()
    print(f"Auth success: {success}")
    if success:
        print("Fetching positions...")
        pos = api.get_all_positions()
        print(f"Positions: {len(pos)}")
        print("Fetching balance...")
        bal = api.get_account_balance()
        print(f"Balance: {bal}")

asyncio.run(main())
