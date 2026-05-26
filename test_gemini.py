import os
import requests
import json

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("No API Key")
    exit(1)

prompt = "Trova 2 asset speculativi in JSON: [\"Asset1\", \"Asset2\"]"
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={api_key}"
payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "tools": [{"googleSearch": {}}]
}
headers = {"Content-Type": "application/json"}
try:
    response = requests.post(url, json=payload, headers=headers)
    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)
except Exception as e:
    print("ERROR:", str(e))
