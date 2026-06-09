import os, requests, pandas as pd
from dotenv import load_dotenv

load_dotenv()
email, api_key, api_sec = os.getenv("CAPITAL_EMAIL"), os.getenv("CAPITAL_API_KEY"), os.getenv("CAPITAL_API_SECRET")

# Login
res = requests.post("https://demo-api-capital.backend-capital.com/api/v1/session", json={"identifier": email, "password": api_sec}, headers={"X-CAP-API-KEY": api_key, "Content-Type": "application/json"})
auth = {"X-CAP-API-KEY": api_key, "CST": res.headers.get("CST"), "X-SECURITY-TOKEN": res.headers.get("X-SECURITY-TOKEN")}

epic = "BTCUSD"
resolution = "MINUTE_15"
max_candles = 1000

print(f"Testing backwards loop for {epic} {resolution}...")
url1 = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution={resolution}&max={max_candles}"
data1 = requests.get(url1, headers=auth).json().get('prices', [])
if not data1:
    print("Failed first request")
    exit()
    
oldest_time = data1[0]['snapshotTime']
print(f"First request got {len(data1)} candles. Oldest: {oldest_time}")

# Try second request ending right before the oldest_time
# Capital API expects URL encoded strings?
# No, let's try just passing `before` or `to`
# Sometimes the param is `before` or `to`? Let's check typical lightstreamer / IG endpoints:
url2 = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution={resolution}&max={max_candles}&before={oldest_time}"
data2 = requests.get(url2, headers=auth).json().get('prices', [])
if data2:
    print(f"Second request with 'before' got {len(data2)}. Oldest: {data2[0]['snapshotTime']}")
else:
    # Try 'to' instead
    url3 = f"https://demo-api-capital.backend-capital.com/api/v1/prices/{epic}?resolution={resolution}&max={max_candles}&to={oldest_time}"
    data3 = requests.get(url3, headers=auth).json().get('prices', [])
    if data3:
        print(f"Second request with 'to' got {len(data3)}. Oldest: {data3[0]['snapshotTime']}")
    else:
        print(requests.get(url3, headers=auth).text)
