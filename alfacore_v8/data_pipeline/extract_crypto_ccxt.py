import ccxt
import pandas as pd
import time
from datetime import datetime, timezone
import os

def extract_binance_crypto(symbol='BTC/USDT', timeframe='15m', dal_anno=2024):
    """
    Estrae dati M15 da KuCoin in blocchi da 1000 candele usando CCXT nativo.
    Rispetta rigorosamente i rate limits senza appoggiarsi a software di terze parti.
    """
    print(f"🔄 Inizio estrazione {symbol} ({timeframe}) dal {dal_anno} via KuCoin CCXT...")
    exchange = ccxt.kucoin({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    
    since = exchange.parse8601(f'{dal_anno}-01-01T00:00:00Z')
    limit = 1000
    all_ohlcv = []
    
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1  # Prossima iterazione millisecondo successivo
            
            # Stampa progresso e previeni Rate Limiting
            current_date = datetime.fromtimestamp(since / 1000.0, tz=timezone.utc).strftime('%Y-%m-%d')
            print(f"Scaricato blocco fino al {current_date}... (Totale candele: {len(all_ohlcv)})")
            
            time.sleep(exchange.rateLimit / 1000)
            
        except ccxt.NetworkError as e:
            print(f"⚠️ Errore di rete: {e}. Ritento tra 5 secondi...")
            time.sleep(5)
        except ccxt.ExchangeError as e:
            print(f"❌ Errore Exchange: {e}")
            break
            
    df = pd.DataFrame(all_ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['Datetime'] = pd.to_datetime(df['Timestamp'], unit='ms')
    df.drop(columns=['Timestamp'], inplace=True)
    
    # Rimuovi eventuali duplicati
    df.drop_duplicates(subset=['Datetime'], inplace=True)
    df.sort_values('Datetime', inplace=True)
    
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(output_dir, "raw_crypto_M15.csv")
    df.to_csv(output_file, index=False)
    print(f"✅ Estrazione Crypto completata: {len(df)} candele salvate in {output_file}.")

if __name__ == "__main__":
    extract_binance_crypto()
