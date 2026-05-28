import time
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MultiProviderAPI:
    """
    Data Rotator che distribuisce le richieste OHLCV su più provider gratuiti (Binance, Coinbase, Yahoo)
    per evitare blocchi per limiti di rateo e bypassare le restrizioni di un singolo broker.
    """
    def __init__(self, capital_api):
        self.capital_api = capital_api

    def _map_epic(self, epic, provider):
        # Mappa i simboli di Capital.com a quelli dei provider
        if provider == "binance":
            # BTCUSD -> BTCUSDT
            if "USD" in epic and epic != "USDJPY" and epic != "EURUSD" and epic != "GBPUSD" and epic != "AUDUSD" and epic != "NZDUSD":
                return epic.replace("USD", "USDT")
            return None
            
        elif provider == "coinbase":
            # BTCUSD -> BTC-USD
            if "USD" in epic and epic != "USDJPY" and epic != "EURUSD" and epic != "GBPUSD" and epic != "AUDUSD" and epic != "NZDUSD":
                return epic.replace("USD", "-USD")
            return None
            
        elif provider == "yahoo":
            # Mapping manuale dei più comuni
            mapping = {
                "GOLD": "GC=F",
                "OIL_BRENT": "BZ=F",
                "OIL_CRUDE": "CL=F",
                "NATURALGAS": "NG=F",
                "BTCUSD": "BTC-USD",
                "ETHUSD": "ETH-USD",
                "EURUSD": "EURUSD=X",
                "GBPUSD": "GBPUSD=X",
                "USDJPY": "JPY=X",
                "EURJPY": "EURJPY=X",
                "GBPJPY": "GBPJPY=X",
                "EURGBP": "EURGBP=X",
                "USDCAD": "CAD=X",
                "AUDUSD": "AUDUSD=X",
                "NZDUSD": "NZDUSD=X",
                "US30": "^DJI",
                "SP500": "^GSPC",
                "NAS100": "^IXIC",
                "HK50": "^HSI",
                "GER40": "^GDAXI",
            }
            if epic in mapping:
                return mapping[epic]
            # Altrimenti prova il ticker liscio (azioni USA)
            return epic
            
        return epic

    def get_historical_prices(self, epic: str, hours: int = 100) -> list:
        """
        Ritorna la lista standardizzata compatibile con XGBoost:
        [{'openPrice': {'bid': ...}, 'highPrice': {'bid': ...}, 'lowPrice': {'bid': ...}, 'closePrice': {'bid': ...}, 'lastTradedVolume': ...}]
        """
        # Determina la natura dell'asset per instradarlo al server migliore
        is_crypto = epic.endswith("USD") and epic not in ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]
        
        if is_crypto:
            providers = ["binance", "coinbase", "yahoo", "capital"]
        else:
            providers = ["yahoo", "capital"]
            
        for provider in providers:
            try:
                mapped_symbol = self._map_epic(epic, provider)
                if not mapped_symbol and provider != "capital":
                    continue
                    
                if provider == "binance":
                    data = self._fetch_binance(mapped_symbol, hours)
                elif provider == "coinbase":
                    data = self._fetch_coinbase(mapped_symbol, hours)
                elif provider == "yahoo":
                    data = self._fetch_yahoo(mapped_symbol, hours)
                elif provider == "capital":
                    data = self.capital_api.get_historical_prices(epic, hours)
                    
                if data and len(data) > 0:
                    logger.info(f"✅ Dati {epic} scaricati da {provider.upper()} ({len(data)} candele)")
                    return data
            except Exception as e:
                logger.warning(f"⚠️ Provider {provider} fallito per {epic}: {e}")
                
        logger.error(f"❌ Tutti i provider falliti per {epic}")
        return []

    def _fetch_binance(self, symbol, limit):
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            klines = resp.json()
            result = []
            for k in klines:
                result.append({
                    "openPrice": {"bid": float(k[1])},
                    "highPrice": {"bid": float(k[2])},
                    "lowPrice": {"bid": float(k[3])},
                    "closePrice": {"bid": float(k[4])},
                    "lastTradedVolume": float(k[5])
                })
            return result
        return []

    def _fetch_coinbase(self, symbol, limit):
        url = f"https://api.exchange.coinbase.com/products/{symbol}/candles?granularity=3600"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            klines = resp.json()
            result = []
            # Coinbase ritorna: [ [time, low, high, open, close, volume], ... ]
            # Ed è ordinato dal più recente al più vecchio, quindi invertiamo!
            for k in reversed(klines[:limit]):
                result.append({
                    "openPrice": {"bid": float(k[3])},
                    "highPrice": {"bid": float(k[2])},
                    "lowPrice": {"bid": float(k[1])},
                    "closePrice": {"bid": float(k[4])},
                    "lastTradedVolume": float(k[5])
                })
            return result
        return []

    def _fetch_yahoo(self, symbol, limit):
        # 1mo with 1h interval usually provides ~150-160 candles
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=1mo"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            result = data['chart']['result'][0]
            indicators = result['indicators']['quote'][0]
            
            opens = indicators.get('open', [])
            highs = indicators.get('high', [])
            lows = indicators.get('low', [])
            closes = indicators.get('close', [])
            volumes = indicators.get('volume', [])
            
            out = []
            for i in range(len(opens)):
                if opens[i] is not None and closes[i] is not None:
                    out.append({
                        "openPrice": {"bid": float(opens[i])},
                        "highPrice": {"bid": float(highs[i])},
                        "lowPrice": {"bid": float(lows[i])},
                        "closePrice": {"bid": float(closes[i])},
                        "lastTradedVolume": float(volumes[i] if volumes[i] is not None else 0)
                    })
            return out[-limit:]
        return []
