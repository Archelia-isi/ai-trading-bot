import requests

def search_ticker(query):
    url = f"https://query2.finance.yahoo.com/v1/finance/search"
    params = {"q": query, "quotesCount": 1, "newsCount": 0}
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, params=params, headers=headers)
    if res.status_code == 200:
        data = res.json()
        if "quotes" in data and len(data["quotes"]) > 0:
            return data["quotes"][0]["symbol"]
    return None

print("Apple:", search_ticker("Apple"))
print("Bitcoin:", search_ticker("Bitcoin"))
print("Oro:", search_ticker("Gold"))
