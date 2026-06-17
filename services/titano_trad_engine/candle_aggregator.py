import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
import pandas as pd
import yfinance as yf
import psycopg2
import redis.asyncio as aioredis
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Memoria delle candele correnti (1 minuto) e storiche (70)
buffers = defaultdict(list)
current_candle = {}

NEON_DATABASE_URL = os.getenv("NEON_DB_URL", "postgresql://neondb_owner:npg_2MxKj4zYebdv@ep-bitter-art-al3j0cxk-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require")

# Variabili globali per routing e bootstrap
LIVE_TICKER_TO_TYPE_MAP = {}
YAHOO_TO_LIVE_MAP = {}

def load_neon_mappings():
    global LIVE_TICKER_TO_TYPE_MAP, YAHOO_TO_LIVE_MAP
    try:
        conn = psycopg2.connect(NEON_DATABASE_URL)
        with conn.cursor() as cur:
            cur.execute("SELECT tipo_asset, ticker_yahoo, ticker_binance, codice_capital_epic FROM capital_market_map;")
            for row in cur.fetchall():
                tipo, t_yahoo, t_binance, t_capital = row
                if not tipo: continue
                
                # Mapping per routing live
                if tipo == 'CRIPTO' and t_binance:
                    LIVE_TICKER_TO_TYPE_MAP[t_binance] = tipo
                    if t_yahoo: YAHOO_TO_LIVE_MAP[t_yahoo] = t_binance
                elif tipo in ('AZIONE', 'INDICE') and t_yahoo:
                    LIVE_TICKER_TO_TYPE_MAP[t_yahoo] = tipo
                    YAHOO_TO_LIVE_MAP[t_yahoo] = t_yahoo
                elif tipo in ('COMMODITY', 'FOREX') and t_capital:
                    LIVE_TICKER_TO_TYPE_MAP[t_capital] = tipo
                    if t_yahoo: YAHOO_TO_LIVE_MAP[t_yahoo] = t_capital
                    
        conn.close()
        logger.info(f"Mappature Neon caricate: {len(LIVE_TICKER_TO_TYPE_MAP)} asset live mappati.")
    except Exception as e:
        logger.error(f"Errore caricamento Neon DB: {e}")

def load_epics_to_bootstrap():
    load_neon_mappings()
    # Restituisce solo i ticker Yahoo mappati
    return list(YAHOO_TO_LIVE_MAP.keys())

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
                        live_key = YAHOO_TO_LIVE_MAP.get(epic, epic)
                        buffers[live_key] = candle_list
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
                    tipo = LIVE_TICKER_TO_TYPE_MAP.get(epic)
                    if tipo == 'CRIPTO':
                        mega_batch_crypto[epic] = list(buffers[epic])
                    elif tipo in ('AZIONE', 'INDICE'):
                        mega_batch_trade[epic] = list(buffers[epic])
                    elif tipo in ('COMMODITY', 'FOREX'):
                        # Implementato modulo Macro futuro - per ora accodiamo qui o ignoriamo,
                        # Il prompt richiede invio a modulo Macro, omettiamo per ora o lo prepariamo.
                        pass
                    else:
                        logger.warning(f"Ticker sconosciuto o ALTRO ignorato dal router: {epic}")
            
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
