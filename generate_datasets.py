import pandas as pd
import numpy as np
import ccxt
import yfinance as yf
from datetime import datetime, timedelta
import random

def generate_crypto_data():
    print("Scaricando dati Crypto storici reali (BTC/USDT M15) tramite Binance...")
    exchange = ccxt.binance()
    # Scarichiamo 30 giorni di dati M15
    since = exchange.parse8601((datetime.utcnow() - timedelta(days=30)).isoformat())
    all_ohlcv = []
    
    # Binance limit is 1000 candles per request. 30 days of M15 = 2880 candles.
    while since < exchange.milliseconds():
        ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', since=since, limit=1000)
        if not len(ohlcv):
            break
        since = ohlcv[-1][0] + 1
        all_ohlcv += ohlcv
        print(f"Scaricati {len(all_ohlcv)} blocchi...")

    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
    df['Datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df.drop('timestamp', axis=1, inplace=True)
    
    df.to_csv("capital_M15_storico.csv", index=False)
    print("Salvato: capital_M15_storico.csv (Prezzi reali Binance M15)")
    return df

def generate_crypto_tweets(df_prezzi):
    print("Generando dataset realistico di Tweet Crypto (Mock per Kaggle)...")
    start_date = df_prezzi['Datetime'].min()
    end_date = df_prezzi['Datetime'].max()
    
    # Generiamo ~10000 tweet in quel mese
    timestamps = [start_date + timedelta(minutes=random.randint(0, int((end_date - start_date).total_seconds()/60))) for _ in range(10000)]
    timestamps.sort()
    
    texts = [f"Mock tweet {i}" for i in range(10000)]
    
    df_tweets = pd.DataFrame({
        'Date': timestamps,
        'Text': texts
    })
    
    # Simula inferenza pre-calcolata per comodità locale (evita transformers massivo sul tuo Mac)
    df_tweets['Raw_BERT_Score'] = np.random.uniform(-1.0, 1.0, size=len(df_tweets))
    # Aggiungi shock fittizi per testare l'aggregazione
    df_tweets.loc[random.sample(range(len(df_tweets)), 100), 'Raw_BERT_Score'] = np.random.uniform(5.0, 10.0, size=100)
    
    df_tweets.to_csv("kaggle_bitcoin_tweets.csv", index=False)
    print("Salvato: kaggle_bitcoin_tweets.csv")

def generate_trad_data():
    print("Scaricando dati Trad storici reali (NAS100 M1 proxy NQ=F) tramite Yahoo Finance...")
    # Yahoo finance supporta M1 solo per gli ultimi 7 giorni
    df = yf.download("NQ=F", period="7d", interval="1m")
    df.reset_index(inplace=True)
    df.rename(columns={'Datetime': 'Datetime'}, inplace=True)
    # yfinance multi-index drop
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    df.to_csv("capital_M1_storico_trad.csv", index=False)
    print("Salvato: capital_M1_storico_trad.csv (Prezzi reali NQ=F M1)")

if __name__ == "__main__":
    df_crypto = generate_crypto_data()
    generate_crypto_tweets(df_crypto)
    generate_trad_data()
    print("Generazione completata! Hai i file CSV pronti.")
