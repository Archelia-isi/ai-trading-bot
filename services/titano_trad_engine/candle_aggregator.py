import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import redis.asyncio as aioredis
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Memoria delle candele correnti (1 minuto) e storiche (70)
buffers = defaultdict(list)
current_candle = {}

def load_epics_to_bootstrap():
    epics = []
    # 1. Ticker USA
    usa_path = os.path.join(os.path.dirname(__file__), "..", "market_streamer_engine", "usa_tickers.json")
    if os.path.exists(usa_path):
        with open(usa_path, 'r') as f:
            usa_list = json.load(f)
            epics.extend(usa_list[:1000]) # Limitiamo a 1000 per evitare lunghi blocchi e rate limits massivi
    
    # 2. Ticker Crypto Comuni
    crypto = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "XRP-USD", "ADA-USD"]
    epics.extend(crypto)
    
    # 3. Ticker Europei/Asiatici (quelli standard di Yahoo)
    intl = ["UCG.MI", "ISP.MI", "ENEL.MI", "RACE.MI", "MC.PA", "ASML.AS", "SIE.DE", "SAP.DE"]
    epics.extend(intl)
    
    return list(set(epics))

def bootstrap_history(epics_list):
    """ Esegue il warm-up massivo con yfinance in blocchi per evitare blocchi IP. """
    logger.info(f"⏳ Avvio Bootstrap Storico su {len(epics_list)} asset tramite yfinance...")
    
    chunk_size = 300
    for i in range(0, len(epics_list), chunk_size):
        chunk = epics_list[i:i + chunk_size]
        tickers_str = " ".join(chunk)
        try:
            # Scarichiamo gli ultimi 3 giorni (risoluzione 1m), poi prendiamo solo le ultime 70 candele
            data = yf.download(tickers_str, period="3d", interval="1m", group_by="ticker", threads=True, progress=False)
            
            for epic in chunk:
                try:
                    if len(chunk) == 1:
                        df = data
                    else:
                        df = data[epic]
                    
                    df = df.dropna()
                    if len(df) == 0:
                        continue
                        
                    # Prendi le ultime 70 righe
                    df_tail = df.tail(70)
                    candle_list = []
                    for idx, row in df_tail.iterrows():
                        candle_list.append({
                            "open": float(row['Open']),
                            "high": float(row['High']),
                            "low": float(row['Low']),
                            "close": float(row['Close']),
                            "volume": float(row.get('Volume', 0))
                        })
                    
                    if len(candle_list) > 0:
                        buffers[epic] = candle_list
                except Exception as e:
                    pass
            logger.info(f"✅ Bootstrap chunk {i}-{i+chunk_size} completato.")
            time.sleep(1) # Courtesy sleep
        except Exception as e:
            logger.error(f"❌ Errore download chunk: {e}")
            
    logger.info(f"🚀 Bootstrap Completato! Storico acquisito per {len(buffers)} asset (su {len(epics_list)} richiesti).")

async def candle_closer_loop(r):
    """ Controlla ogni secondo se il minuto è cambiato, chiude le candele e invia i mega-batch """
    last_minute = datetime.utcnow().replace(second=0, microsecond=0).timestamp()
    while True:
        await asyncio.sleep(1)
        now = datetime.utcnow()
        current_minute = now.replace(second=0, microsecond=0).timestamp()
        
        if current_minute > last_minute:
            # Minuto scattato!
            mega_batch_trade = {}
            mega_batch_crypto = {}
            
            for epic, candle in list(current_candle.items()):
                # Push nel buffer storico
                buffers[epic].append({
                    "open": candle["open"], "high": candle["high"], 
                    "low": candle["low"], "close": candle["close"], "volume": candle["volume"]
                })
                # Truncate a 70 elementi per Titano V8
                if len(buffers[epic]) > 70:
                    buffers[epic].pop(0)
                    
                # Reset della candela
                current_candle[epic] = {
                    "open": candle["close"], "high": candle["close"], 
                    "low": candle["close"], "close": candle["close"], 
                    "volume": 0, "minute_start": current_minute
                }
                
                # Invio al cervello AI solo se abbiamo lo storico pieno (70 slot)
                if len(buffers[epic]) >= 70:
                    if "USD" in epic or "BTC" in epic or "ETH" in epic:
                        mega_batch_crypto[epic] = list(buffers[epic])
                    else:
                        mega_batch_trade[epic] = list(buffers[epic])
            
            if mega_batch_trade:
                await r.publish("market_candles_stream", json.dumps(mega_batch_trade))
                logger.info(f"📤 Inviato Mega-Batch TRADE (market_candles_stream) con {len(mega_batch_trade)} asset.")
                
            if mega_batch_crypto:
                await r.publish("market_candles_crypto", json.dumps(mega_batch_crypto))
                logger.info(f"📤 Inviato Mega-Batch CRYPTO (market_candles_crypto) con {len(mega_batch_crypto)} asset.")
                
            last_minute = current_minute

async def run_aggregator():
    logger.info("Avvio Candle Aggregator (Time-Series Buffer)...")
    
    # Esegui bootstrap bloccante off-thread
    await asyncio.to_thread(bootstrap_history, load_epics_to_bootstrap())
    
    r = await aioredis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe("market_updates_global", "market_updates_crypto")
    
    asyncio.create_task(candle_closer_loop(r))
    
    async for message in pubsub.listen():
        if message['type'] == 'message':
            try:
                tick = json.loads(message['data'])
                epic = tick.get('ticker')
                price = float(tick.get('close', 0))
                volume = float(tick.get('volume', 0))
                
                if not epic or price <= 0:
                    continue
                    
                now = datetime.utcnow()
                current_minute = now.replace(second=0, microsecond=0).timestamp()
                
                if epic not in current_candle:
                    current_candle[epic] = {
                        "open": price, "high": price, "low": price, "close": price, 
                        "volume": volume, "minute_start": current_minute
                    }
                else:
                    candle = current_candle[epic]
                    if candle["minute_start"] == current_minute:
                        candle["high"] = max(candle["high"], price)
                        candle["low"] = min(candle["low"], price)
                        candle["close"] = price
                        candle["volume"] += volume
                    else:
                        # Edge case: scatto gestito prima del task
                        buffers[epic].append({
                            "open": candle["open"], "high": candle["high"], 
                            "low": candle["low"], "close": candle["close"], "volume": candle["volume"]
                        })
                        if len(buffers[epic]) > 70:
                            buffers[epic].pop(0)
                        current_candle[epic] = {
                            "open": price, "high": price, "low": price, "close": price, 
                            "volume": volume, "minute_start": current_minute
                        }
                        
            except Exception as e:
                pass # Evitiamo spam per parsing errato
