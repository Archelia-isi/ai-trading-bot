import os, requests
from dotenv import load_dotenv

load_dotenv()
email, api_key, api_sec = os.getenv("CAPITAL_EMAIL"), os.getenv("CAPITAL_API_KEY"), os.getenv("CAPITAL_API_SECRET")

res = requests.post("https://demo-api-capital.backend-capital.com/api/v1/session", json={"identifier": email, "password": api_sec}, headers={"X-CAP-API-KEY": api_key, "Content-Type": "application/json"})
cst = res.headers.get("CST")
x_sec = res.headers.get("X-SECURITY-TOKEN")
auth = {"X-CAP-API-KEY": api_key, "CST": cst, "X-SECURITY-TOKEN": x_sec}

from_time = "2024-01-10T00:00:00"
to_time = "2024-01-15T00:00:00"
epic = "US100"

url = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution=MINUTE&from={from_time}&to={to_time}"
data = requests.get(url, headers=auth).json()
print("2024 M1 request returned keys:", data.keys())
if 'prices' in data:
    print(f"Candles downloaded: {len(data['prices'])}")
else:
    print("Error:", data)

# Test M15 for 2024
url2 = f"https://demo-api-capital.backend-capital.com/api/v1/prices/BTCUSD?resolution=MINUTE_15&from={from_time}&to={to_time}"
data2 = requests.get(url2, headers=auth).json()
if 'prices' in data2:
    print(f"BTC M15 Candles downloaded: {len(data2['prices'])}")
else:
    print("Error M15:", data2)
