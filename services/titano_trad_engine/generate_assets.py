import json
import pandas as pd
import requests

def get_sp500():
    try:
        table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
        df = table[0]
        return df['Symbol'].tolist()
    except:
        return ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "NVDA", "JPM", "V", "JNJ"]

def get_nasdaq100():
    try:
        table = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100')
        df = table[4] # Usually table 4 has the components
        if 'Ticker' in df.columns:
            return df['Ticker'].tolist()
        return df['Symbol'].tolist()
    except:
        return ["ADBE", "NFLX", "PEP", "COST", "CSCO"]

def get_crypto():
    return [
        "BTCUSD", "ETHUSD", "XRPUSD", "LTCUSD", "DOGEUSD", 
        "ADAUSD", "DOTUSD", "SOLUSD", "MATICUSD", "LINKUSD",
        "BCHUSD", "UNIUSD", "AVAXUSD", "XLMUSD", "ATOMUSD",
        "BTC-USD", "ETH-USD", "XRP-USD", "SOL-USD"
    ]

def get_forex_commodities():
    return [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
        "EURGBP", "EURJPY", "GBPJPY", "GOLD", "SILVER", "OIL_BRENT", "NATURALGAS",
        "US30", "US100", "US500", "GER40", "UK100", "^FCHI", "FTSEMIB.MI", "ESP35",
        "HK50", "^N225", "AUS200"
    ]

def main():
    print("Fetching SP500...")
    sp500 = get_sp500()
    print("Fetching Nasdaq100...")
    nasdaq = get_nasdaq100()
    crypto = get_crypto()
    forex = get_forex_commodities()

    # Combine and deduplicate
    all_assets = list(set(sp500 + nasdaq + crypto + forex))
    
    # Clean tickers
    cleaned = []
    for t in all_assets:
        clean_t = str(t).replace('.', '-')
        cleaned.append(clean_t)
        
    print(f"Total Assets found: {len(cleaned)}")
    
    with open('global_assets.json', 'w') as f:
        json.dump(cleaned, f, indent=4)
    print("global_assets.json created!")

if __name__ == "__main__":
    main()
