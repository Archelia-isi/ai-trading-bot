import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

base_url = "https://demo-api-capital.backend-capital.com/api/v1"
api_key = os.getenv("CAPITAL_API_KEY")
api_secret = os.getenv("CAPITAL_API_SECRET")
email = os.getenv("CAPITAL_EMAIL")

headers = {'Content-Type': 'application/json', 'X-CAP-API-KEY': api_key}
payload = {"identifier": email, "password": api_secret, "encryptedPassword": False}
res = requests.post(f"{base_url}/session", json=payload, headers=headers)
cst = res.headers.get('CST')
x_sec = res.headers.get('X-SECURITY-TOKEN')

headers['CST'] = cst
headers['X-SECURITY-TOKEN'] = x_sec

# Test POST /positions
order_payload = {
    "epic": "BTCUSD",
    "direction": "BUY",
    "size": 0.01,
    "guaranteedStop": False
}
print("Invio ordine...")
order_res = requests.post(f"{base_url}/positions", json=order_payload, headers=headers)
print("STATUS:", order_res.status_code)
print("RESPONSE:", order_res.text)
