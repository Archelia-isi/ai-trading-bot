import os
import requests
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime, timedelta

load_dotenv()

email = os.getenv("CAPITAL_EMAIL")
api_key = os.getenv("CAPITAL_API_KEY")
api_sec = os.getenv("CAPITAL_API_SECRET")

url_session = "https://demo-api-capital.backend-capital.com/api/v1/session"
headers = {"X-CAP-API-KEY": api_key, "Content-Type": "application/json"}
payload = {"identifier": email, "password": api_sec}
res = requests.post(url_session, json=payload, headers=headers)
cst = res.headers.get("CST")
x_sec = res.headers.get("X-SECURITY-TOKEN")

auth_headers = {
    "X-CAP-API-KEY": api_key,
    "CST": cst,
    "X-SECURITY-TOKEN": x_sec
}

def get_capital_prices(epic, resolution="MINUTE_15", max_points=1000):
    url_prices = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution={resolution}&max={max_points}"
    res_prices = requests.get(url_prices, headers=auth_headers)
    if res_prices.status_code == 200:
        data = res_prices.json()
        return data.get("prices", [])
    print("Error:", res_prices.text)
    return []

print("Fetching BTCUSD M15...")
btc_prices = get_capital_prices("BTCUSD", "MINUTE_15", 1000)
print(f"BTCUSD returned {len(btc_prices)} points. Earliest: {btc_prices[0]['snapshotTime'] if btc_prices else 'N/A'}")

print("Fetching US100 M1...")
nas_prices = get_capital_prices("US100", "MINUTE", 1000)
print(f"US100 returned {len(nas_prices)} points. Earliest: {nas_prices[0]['snapshotTime'] if nas_prices else 'N/A'}")
