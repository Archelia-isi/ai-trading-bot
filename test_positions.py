import os
import json

os.environ["CAPITAL_API_KEY"] = "JoAgiPRKn7ZPpyuc"
os.environ["CAPITAL_API_SECRET"] = "Salvatore1!"
os.environ["CAPITAL_EMAIL"] = "salvatore@immobiliareizzo.com"
os.chdir("services/audit_engine")
import sys
sys.path.append(".")
from capital_api import CapitalComAPI

api = CapitalComAPI()
if api.authenticate():
    positions = api.get_all_positions()
    if positions:
        print(json.dumps(positions[0], indent=2))
    else:
        print("No open positions")
        
    margin = api.get_margin_info()
    print("Margin Info:")
    print(json.dumps(margin, indent=2))
    
    accounts = api.get_account_balance()
    print(f"Balance: {accounts}")
    
    # Raw accounts
    import requests
    response = requests.get(f"{api.base_url}/accounts", headers=api._get_headers(with_auth=True))
    print("Raw accounts response:")
    print(json.dumps(response.json(), indent=2))
