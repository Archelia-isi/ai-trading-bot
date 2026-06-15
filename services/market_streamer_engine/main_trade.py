import asyncio
import json
import logging
import os
import time
import websockets
import redis.asyncio as aioredis
from datetime import datetime
from capital_api import CapitalComAPI
from database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

db = DatabaseManager()
db_queue = asyncio.Queue()

# Liste fisse
CRYPTO_MAJORS_1 = ["BTCUSD", "ETHUSD", "SOLUSD"]
CRYPTO_MAJORS_2 = ["DOGEUSD", "XRPUSD", "ADAUSD"]

STOCK_MAJORS_1 = ["AAPL", "MSFT", "NVDA", "AMZN"]
STOCK_MAJORS_2 = ["META", "TSLA", "SPY", "QQQ"]

# Liste rotazionali (Global Pool)
GLOBAL_CRYPTO = [
    "LTCUSD", "BCHUSD", "DOTUSD", "LINKUSD", "XLMUSD", "UNIUSD", "AVAXUSD",
    "ATOMUSD", "FILUSD", "AAVEUSD", "MKRUSD", "SNXUSD", "COMPUSD", "EOSUSD"
]

ASIAN_STOCKS = [
    "7203.T", "6758.T", "7267.T", "TSM", "BABA", "JD", "BIDU", 
    "INFY", "HDB", "TTM", "0700.HK"
]

EUROPEAN_STOCKS = [
    "MC.PA", "OR.PA", "TTE.PA", "SU.PA", "ASML.AS", "SAP.DE", "SIE.DE", 
    "VOW3.DE", "ALV.DE", "ENEL.MI", "RACE.MI", "UCG.MI", "ISP.MI", "ENI.MI",
    "IBE.MC", "SAN.MC", "ITX.MC", "HSBA.L", "SHEL.L", "AZN.L", "NVO", "NVS"
]

GLOBAL_MARKETS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "GOLD", "USOIL", "NATURALGAS",
    "EURGBP", "EURJPY", "GBPJPY", "SILVER", "COPPER", "PALLADIUM",
    "JP225", "HK50", "IN50", "AU200", "CN50", "IT40", "DE40", "FR40", "UK100", "ES35", "EU50", "US500", "US100"
]

try:
    from global_1000 import TOP_1000_STOCKS
    GLOBAL_MARKETS += TOP_1000_STOCKS
except ImportError:
    pass

GLOBAL_MARKETS += ASIAN_STOCKS + EUROPEAN_STOCKS

# MAPPATURA (Ticker Standard -> Capital EPIC)
TICKER_TO_EPIC = {
    "7203.T": "7203", "6758.T": "SNE", "7267.T": "7267", "0700.HK": "0700",
    "MC.PA": "MCFR", "OR.PA": "OR", "TTE.PA": "TTEF", "SU.PA": "SUP", "ASML.AS": "ASMLNL",
    "SAP.DE": "SAPD", "SIE.DE": "SIE", "VOW3.DE": "VOW3", "ALV.DE": "ALVD",
    "ENEL.MI": "ENEL", "RACE.MI": "RACEM", "UCG.MI": "UCG", "ISP.MI": "ISP", "ENI.MI": "ENI",
    "IBE.MC": "IBEES", "SAN.MC": "SANE", "ITX.MC": "ITX",
    "HSBA.L": "HSBC", "SHEL.L": "SHELGB", "AZN.L": "AZNL", "NVS": "NOVN"
}

# MAPPATURA INVERSA (Capital EPIC -> Ticker Standard)
EPIC_TO_TICKER = {v: k for k, v in TICKER_TO_EPIC.items()}

def get_capital_epic(ticker: str) -> str:
    return TICKER_TO_EPIC.get(ticker, ticker)

def get_standard_ticker(epic: str) -> str:
    return EPIC_TO_TICKER.get(epic, epic)

api = CapitalComAPI()

# Memoria globale per aggregazione tick -> candele
# structure: { epic: { "minute_ts": 12345000, "open": X, "high": X, "low": X, "close": X, "ticks": 0 } }
live_candles = {}

# Memoria storica: { epic: [ {candle1}, {candle2}... (fino a 30) ] }
historical_candles = {}

async def prefill_historical_data(epic: str):
    """Precarica le ultime 30 candele a 1 minuto via REST per saltare il warm-up di 30 minuti."""
    try:
        # Chiamata REST manuale a MINUTO (Capital API base url)
        url = f"{api.base_url}/prices/{get_capital_epic(epic)}?resolution=MINUTE&max=70"
        import requests
        response = requests.get(url, headers=api._get_headers(with_auth=True), timeout=10)
        
        if response.status_code == 200:
            prices = response.json().get('prices', [])
            # prices è una lista di dict { snapshotTime: ..., openPrice: {bid}, highPrice, lowPrice, closePrice }
            candles = []
            for p in prices:
                o = p.get('openPrice', {}).get('bid', 0.0)
                h = p.get('highPrice', {}).get('bid', 0.0)
                l = p.get('lowPrice', {}).get('bid', 0.0)
                c = p.get('closePrice', {}).get('bid', 0.0)
                candles.append({"open": o, "high": h, "low": l, "close": c})
                
            historical_candles[epic] = candles
            logger.info(f"📊 [Memoria] Buffer riempito ({len(candles)}/70 candele) per {epic}")
        else:
            historical_candles[epic] = []
            logger.warning(f"⚠️ [Memoria] Impossibile scaricare storico per {epic}, warm-up richiesto.")
    except Exception as e:
        historical_candles[epic] = []
        logger.error(f"Errore prefill per {epic}: {e}")

def process_tick(epic: str, price: float):
    """Prende un tick (prezzo) in tempo reale e lo compatta in una candela da 1 minuto."""
    now = datetime.utcnow()
    current_minute = now.replace(second=0, microsecond=0).timestamp()
    
    if epic not in live_candles:
        # Inizializza nuova candela per questo epic
        live_candles[epic] = {
            "minute_ts": current_minute,
            "open": price, "high": price, "low": price, "close": price, "ticks": 1
        }
    else:
        c = live_candles[epic]
        if current_minute > c["minute_ts"]:
            # IL MINUTO E' SCADUTO! La candela è chiusa. Salviamola nella storia.
            if epic not in historical_candles:
                historical_candles[epic] = []
            
            historical_candles[epic].append({
                "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]
            })
            
            # --- SALVATAGGIO IN DATA LAKE (Coda Asincrona) ---
            db_candle_format = {
                "timestamp": int(c["minute_ts"] * 1000), # Capital.com usa millisecondi
                "openPrice": {"bid": c["open"]},
                "highPrice": {"bid": c["high"]},
                "lowPrice": {"bid": c["low"]},
                "closePrice": {"bid": c["close"]},
                "lastTradedVolume": c["ticks"]
            }
            db_queue.put_nowait((epic, [db_candle_format]))
            
            # Manteniamo solo le ultime 70 candele per l'inferenza V8
            if len(historical_candles[epic]) > 70:
                historical_candles[epic].pop(0)
                
            # Avviamo la nuova candela del nuovo minuto
            live_candles[epic] = {
                "minute_ts": current_minute,
                "open": price, "high": price, "low": price, "close": price, "ticks": 1
            }
        else:
            # Stesso minuto: aggiorniamo massimi, minimi e chiusura
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
            c["ticks"] += 1

async def ws_handler_fixed(socket_id: int, role: str, epics_list: list, r: aioredis.Redis):
    """Gestisce una singola connessione WebSocket verso Capital.com (Asset Fissi)"""
    if not api.is_authenticated:
        return

    headers = {
        'CST': api.cst_token,
        'X-SECURITY-TOKEN': api.x_security_token,
        'X-CAP-API-KEY': str(api.api_key)
    }
    
    uri = "wss://api-streaming-capital.backend-capital.com/connect"
    logger.info(f"🟢 [Socket {socket_id} - {role}] Avvio connessione Fissa...")
    
    for epic in epics_list:
        await prefill_historical_data(epic)
    
    while True:
        try:
            async with websockets.connect(uri, additional_headers=headers, ping_interval=30, ping_timeout=10) as ws:
                logger.info(f"✅ [Socket {socket_id} - {role}] Connesso con successo!")
                
                subscribe_msg = {
                    "destination": "marketdata.subscribe",
                    "payload": { "epics": epics_list }
                }
                await ws.send(json.dumps(subscribe_msg))
                
                async for message in ws:
                    data = json.loads(message)
                    if "payload" in data:
                        tick = data["payload"]
                        epic = tick.get("epic")
                        if epic:
                            standard_ticker = get_standard_ticker(epic)
                        bid = tick.get("bid")
                        ask = tick.get("ofr")
                        if epic and bid and ask:
                            mid_price = (bid + ask) / 2
                            process_tick(standard_ticker, mid_price)
                            
        except Exception as e:
            logger.error(f"❌ [Socket {socket_id}] Disconnesso o errore: {e}. Riconnessione...")
            await asyncio.sleep(5)

async def ws_handler_rotational(socket_id: int, role: str, pool: list, r: aioredis.Redis, chunk_size: int = 5, rotation_minutes: int = 10):
    """WebSocket Rotazionale: Scansiona il mercato a blocchi ogni X minuti"""
    if not api.is_authenticated: return
    headers = {'CST': api.cst_token, 'X-SECURITY-TOKEN': api.x_security_token, 'X-CAP-API-KEY': str(api.api_key)}
    uri = "wss://api-streaming-capital.backend-capital.com/connect"
    
    while True:
        # Mescola o cicla (qui prendiamo blocchi in ordine per semplicità)
        import random
        random.shuffle(pool)
        chunk = pool[:chunk_size]
        
        logger.info(f"🔄 [Socket {socket_id} - {role}] Rotazione Radar -> Scansionando: {chunk}")
        
        for epic in chunk:
            await prefill_historical_data(epic)
            await asyncio.sleep(0.2) # Evita il ban API durante il caricamento di massa
            
        try:
            async with websockets.connect(uri, additional_headers=headers, ping_interval=30, ping_timeout=10) as ws:
                capital_epics = [get_capital_epic(e) for e in chunk]
                payload = {"destination": "marketdata.subscribe", "payload": {"epics": capital_epics}}
                await ws.send(json.dumps(payload))
                
                start_time = time.time()
                async for message in ws:
                    data = json.loads(message)
                    if "payload" in data:
                        tick = data["payload"]
                        epic = tick.get("epic")
                        if epic:
                            standard_ticker = get_standard_ticker(epic)
                        bid = tick.get("bid")
                        ask = tick.get("ofr")
                        if epic and bid and ask:
                            mid_price = (bid + ask) / 2
                            process_tick(standard_ticker, mid_price)
                            
                    # Controlla se è tempo di ruotare
                    if time.time() - start_time > (rotation_minutes * 60):
                        logger.info(f"⏱️ [Socket {socket_id} - {role}] Fine turno per {chunk}. Sgancio...")
                        break # Esce dal for, chiude il socket, ricomincia il while True con nuovo chunk
                        
        except Exception as e:
            logger.error(f"❌ [Socket {socket_id} - Radar] Errore: {e}. Riprovo...")
            await asyncio.sleep(5)

async def ws_handler_portfolio(socket_id: int, r: aioredis.Redis):
    """Canale 1: Dedicato solo agli asset attualmente aperti in portafoglio."""
    if not api.is_authenticated: return
    headers = {'CST': api.cst_token, 'X-SECURITY-TOKEN': api.x_security_token, 'X-CAP-API-KEY': str(api.api_key)}
    uri = "wss://api-streaming-capital.backend-capital.com/connect"
    
    current_epics = set()
    pubsub = r.pubsub()
    await pubsub.subscribe("portfolio_status")
    
    while True:
        try:
            async with websockets.connect(uri, additional_headers=headers, ping_interval=30, ping_timeout=10) as ws:
                logger.info(f"🟢 [Socket {socket_id} - Custode] Connesso in ascolto sul portafoglio.")
                
                async def listen_ws():
                    async for message in ws:
                        data = json.loads(message)
                        if "payload" in data:
                            tick = data["payload"]
                            epic = tick.get("epic")
                            if epic:
                                standard_ticker = get_standard_ticker(epic)
                            bid, ask = tick.get("bid"), tick.get("ofr")
                            if epic and bid and ask:
                                process_tick(standard_ticker, (bid + ask) / 2)

                async def watch_portfolio():
                    nonlocal current_epics
                    async for message in pubsub.listen():
                        if message['type'] == 'message':
                            try:
                                data = json.loads(message['data'])
                                new_epics = set([p['epic'] for p in data.get('open_positions', [])])
                                
                                if new_epics != current_epics:
                                    # Se ci sono nuovi epic, facciamo prefill
                                    for e in new_epics - current_epics:
                                        await prefill_historical_data(e)
                                        
                                    if new_epics:
                                        capital_epics = [get_capital_epic(e) for e in list(new_epics)]
                                        await ws.send(json.dumps({"destination": "marketdata.subscribe", "payload": {"epics": capital_epics}}))
                                        logger.info(f"🛡️ [Custode] Aggiornata sottoscrizione portafoglio: {list(new_epics)}")
                                        
                                    current_epics = new_epics
                            except Exception as e:
                                pass
                
                # Esegui i due task finché il WS è aperto
                done, pending = await asyncio.wait([asyncio.create_task(listen_ws()), asyncio.create_task(watch_portfolio())], return_when=asyncio.FIRST_COMPLETED)
                for task in pending: task.cancel()
                
        except Exception as e:
            logger.error(f"❌ [Socket {socket_id} - Custode] Errore: {e}. Riconnessione in 5s...")
            await asyncio.sleep(5)

# Task parallelo che ogni 60 secondi invia i dati aggregati (30 candele) a Titano
async def publisher_loop(r: aioredis.Redis):
    while True:
        await asyncio.sleep(60)
        logger.info("📡 [Streamer Publisher] Invio matrici di osservazione a Titano...")
        # Prepariamo un pacchetto con tutti gli asset che hanno almeno 70 candele
        ready_assets = {}
        for epic, candles in historical_candles.items():
            if len(candles) >= 70:
                ready_assets[epic] = candles
        
        if ready_assets:
            await r.publish("market_updates_trade", json.dumps(ready_assets))
            logger.info(f"✅ [TRADE] Inviato pacchetto di inferenza per {len(ready_assets)} asset a Trade Engine.")

# Task in background per salvare nel DB senza bloccare il WebSocket
async def db_writer_loop():
    logger.info("💾 Data Lake Writer Worker avviato.")
    while True:
        try:
            epic, candles = await db_queue.get()
            # Eseguiamo la query bloccante in un thread separato
            await asyncio.to_thread(db.save_candles, epic, candles)
            db_queue.task_done()
        except Exception as e:
            logger.error(f"Errore scrittura Data Lake: {e}")

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    if not api.authenticate():
        return
        
    tasks = []
    # ws_handler_portfolio è già gestito da main_crypto
    
    tasks.append(asyncio.create_task(ws_handler_fixed(2, "Stock Maggiori 1", STOCK_MAJORS_1, r)))
    tasks.append(asyncio.create_task(ws_handler_fixed(3, "Stock Maggiori 2", STOCK_MAJORS_2, r)))
    tasks.append(asyncio.create_task(ws_handler_rotational(4, "Global Radar 1", GLOBAL_MARKETS, r, chunk_size=100, rotation_minutes=2)))
    tasks.append(asyncio.create_task(ws_handler_rotational(5, "Global Radar 2", GLOBAL_MARKETS, r, chunk_size=100, rotation_minutes=2)))
    
    # Task Publisher per Titano
    tasks.append(asyncio.create_task(publisher_loop(r)))
    
    # Task Scrittura Database Data Lake
    tasks.append(asyncio.create_task(db_writer_loop()))
    
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
