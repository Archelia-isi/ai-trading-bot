import os, requests
from dotenv import load_dotenv
load_dotenv()
email, api_key, api_sec = os.getenv("CAPITAL_EMAIL"), os.getenv("CAPITAL_API_KEY"), os.getenv("CAPITAL_API_SECRET")
res = requests.post("https://demo-api-capital.backend-capital.com/api/v1/session", json={"identifier": email, "password": api_sec}, headers={"X-CAP-API-KEY": api_key, "Content-Type": "application/json"})
cst, x_sec = res.headers.get("CST"), res.headers.get("X-SECURITY-TOKEN")
auth = {"X-CAP-API-KEY": api_key, "CST": cst, "X-SECURITY-TOKEN": x_sec}

from_date = "2026-06-01T00:00:00"
to_date = "2026-06-02T00:00:00"
url = f"https://demo-api-capital.backend-capital.com/api/v1/prices/US100?resolution=MINUTE&from={from_date}&to={to_date}"
print(requests.get(url, headers=auth).text[:500])
