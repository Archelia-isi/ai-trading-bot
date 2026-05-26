import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv()

email = os.getenv("CAPITAL_EMAIL")
api_key = os.getenv("CAPITAL_API_KEY")
api_sec = os.getenv("CAPITAL_API_SECRET")

if not all([email, api_key, api_sec]):
    print("Missing credentials")
    sys.exit(1)

# Login
url_session = "https://demo-api-capital.backend-capital.com/api/v1/session"
headers = {"X-CAP-API-KEY": api_key, "Content-Type": "application/json"}
payload = {"identifier": email, "password": api_sec}
res = requests.post(url_session, json=payload, headers=headers)
if res.status_code != 200:
    print("Login failed", res.text)
    sys.exit(1)

cst = res.headers.get("CST")
x_sec = res.headers.get("X-SECURITY-TOKEN")

# Fetch Prices
auth_headers = {
    "X-CAP-API-KEY": api_key,
    "CST": cst,
    "X-SECURITY-TOKEN": x_sec
}
epic = "OIL_CRUDE"
url_prices = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution=DAY&max=250"
res_prices = requests.get(url_prices, headers=auth_headers)
if res_prices.status_code == 200:
    data = res_prices.json()
    prices = data.get("prices", [])
    print(f"Success! Fetched {len(prices)} candles for {epic}.")
    if len(prices) > 0:
        print("Sample:", prices[-1])
else:
    print("Prices failed", res_prices.text)
