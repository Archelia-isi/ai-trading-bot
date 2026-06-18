import requests
import json

base_url = "https://api-capital.backend-capital.com/api/v1"
headers = {'Content-Type': 'application/json', 'X-CAP-API-KEY': "JoAgiPRKn7ZPpyuc"}
payload = {"identifier": "salvatore@immobiliareizzo.com", "password": "Salvatore1!", "encryptedPassword": False}

response = requests.post(f"{base_url}/session", json=payload, headers=headers)
print("Auth Status:", response.status_code)
cst = response.headers.get('CST')
xsec = response.headers.get('X-SECURITY-TOKEN')

if cst and xsec:
    headers['CST'] = cst
    headers['X-SECURITY-TOKEN'] = xsec
    acc_res = requests.get(f"{base_url}/accounts", headers=headers)
    print("Accounts Status:", acc_res.status_code)
    print(json.dumps(acc_res.json(), indent=2))
