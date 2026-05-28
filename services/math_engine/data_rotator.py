import time
import requests
import logging
from datetime import datetime
import sys
from database import DatabaseManager

logger = logging.getLogger(__name__)

class MultiProviderAPI:
    """
    Data Rotator che distribuisce le richieste OHLCV su più provider gratuiti (Binance, Coinbase, Yahoo)
    per evitare blocchi per limiti di rateo e bypassare le restrizioni di un singolo broker.
    Inoltre funziona da Data Lake memorizzando lo storico in DB per limitare l'I/O.
    """
    def __init__(self, capital_api):
        self.capital_api = capital_api
        self.db = DatabaseManager()

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
        Ritorna la lista standardizzata compatibile con XGBoost.
        Sfrutta il Database locale (Data Lake) per minimizzare l'I/O di rete.
        """
        # 1. Recupero dal Data Lake
        saved_candles = self.db.get_candles(epic, hours)
        
        missing_hours = hours
        if saved_candles and len(saved_candles) > 0:
            last_candle_ms = saved_candles[-1]['timestamp']
            now_ms = int(time.time() * 1000)
            diff_hours = int((now_ms - last_candle_ms) / (1000 * 60 * 60))
            missing_hours = diff_hours + 1
            
            if missing_hours <= 0:
                logger.info(f"💾 {epic}: Dati 100% dal DB ({len(saved_candles)}). API saltate.")
                return saved_candles
                
            if missing_hours > hours:
                missing_hours = hours
        
        logger.info(f"🔄 {epic}: Recupero {missing_hours} candele mancanti dai Provider...")

        is_crypto = epic.endswith("USD") and epic not in ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]
        if is_crypto:
            providers = ["binance", "coinbase", "yahoo", "capital"]
        else:
            providers = ["yahoo", "capital"]
            
        new_data = []
        
        for provider in providers:
            try:
                mapped_symbol = self._map_epic(epic, provider)
                if not mapped_symbol and provider != "capital":
                    continue
                    
                if provider == "binance":
                    new_data = self._fetch_binance(mapped_symbol, missing_hours)
                elif provider == "coinbase":
                    new_data = self._fetch_coinbase(mapped_symbol, missing_hours)
                elif provider == "yahoo":
                    new_data = self._fetch_yahoo(mapped_symbol, missing_hours)
                elif provider == "capital":
                    cap_data = self.capital_api.get_historical_prices(epic, missing_hours)
                    # Normalizza timestamp per Capital
                    for c in cap_data:
                        if 'snapshotTimeUTC' in c:
                            dt = datetime.fromisoformat(c['snapshotTimeUTC'].replace('Z', '+00:00'))
                            c['timestamp'] = int(dt.timestamp() * 1000)
                    new_data = cap_data
                    
                if new_data and len(new_data) > 0:
                    logger.info(f"✅ Dati {epic} scaricati da {provider.upper()} ({len(new_data)} candele)")
                    break # Successo, esci dal loop
            except Exception as e:
                logger.warning(f"⚠️ Provider {provider} fallito per {epic}: {e}")
                
        if not new_data and len(saved_candles) == 0:
            logger.error(f"❌ Tutti i provider falliti per {epic} e DB vuoto")
            return []
            
        # 3. Salva le nuove candele nel Data Lake (ignora i duplicati per chiave epic, timestamp)
        if new_data:
            self.db.save_candles(epic, new_data)
            
        # 4. Ritorna le ultime candele aggiornate direttamente dal DB, per avere il pacchetto fuso e ordinato
        return self.db.get_candles(epic, hours)

    def _fetch_binance(self, symbol, limit):
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            klines = resp.json()
            result = []
            for k in klines:
                result.append({
                    "timestamp": int(k[0]),
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
                    "timestamp": int(k[0]) * 1000, # Convert to ms
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
            
            timestamps = result['timestamp']
            
            out = []
            for i in range(len(opens)):
                if opens[i] is not None and closes[i] is not None:
                    out.append({
                        "timestamp": int(timestamps[i]) * 1000,
                        "openPrice": {"bid": float(opens[i])},
                        "highPrice": {"bid": float(highs[i])},
                        "lowPrice": {"bid": float(lows[i])},
                        "closePrice": {"bid": float(closes[i])},
                        "lastTradedVolume": float(volumes[i] if volumes[i] is not None else 0)
                    })
            return out[-limit:]
        return []
