import sys
import os
import aiohttp
import asyncio
import logging
from rapidfuzz import process, fuzz

# Aggiungi `services` al path per importare database
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.neon_lake import NeonLakeManager

logger = logging.getLogger(__name__)

class DynamicAssetResolver:
    def __init__(self):
        self.db = NeonLakeManager()
        self.epic_cache_dict = {}
        # Pre-load cache
        self._warmup_cache()
        
        self.capital_base_url = "https://api-capital.backend-capital.com/api/v1"
        self.api_key = os.getenv("CAPITAL_API_KEY", "")
        self.identifier = os.getenv("CAPITAL_IDENTIFIER", "")
        self.password = os.getenv("CAPITAL_PASSWORD", "")
        self.cst = None
        self.x_sec = None

    def _warmup_cache(self):
        conn = self.db._get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker_feed, epic_capital FROM asset_mapping")
                for row in cur.fetchall():
                    self.epic_cache_dict[row[0]] = row[1]
        except Exception as e:
            logger.error(f"Errore warmup cache: {e}")
        finally:
            conn.close()

    async def authenticate_capital(self):
        if self.cst and self.x_sec: return True
        url = f"{self.capital_base_url}/session"
        payload = {"identifier": self.identifier, "password": self.password}
        headers = {"X-CAP-API-KEY": self.api_key, "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        self.cst = resp.headers.get('CST')
                        self.x_sec = resp.headers.get('X-SECURITY-TOKEN')
                        return True
        except Exception as e:
            logger.error(f"Auth Capital fallita nel Resolver: {e}")
        return False

    async def resolve_epic(self, ticker: str) -> str:
        CORE_FALLBACK_MAP = {
            "AAPL": "AAPL",
            "AAOI": "AAOI",
            "ISP.MI": "ISP",
            "UCG.MI": "UCG",
            "ENEL.MI": "ENEL",
            "RACE.MI": "RACE",
            "SIE.DE": "SIE",
            "SAP.DE": "SAP",
            "MC.PA": "MC",
            "ASML.AS": "ASML",
            "ABTS": "ABTS"
        }
        ticker_upper = ticker.upper()
        if ticker_upper in CORE_FALLBACK_MAP:
            logger.info(f"🎯 [FALLBACK HIT] Risoluzione statica immediata per {ticker_upper} -> {CORE_FALLBACK_MAP[ticker_upper]}")
            return CORE_FALLBACK_MAP[ticker_upper]
            
        # 1. RAM Hit (<1ms)
        if ticker in self.epic_cache_dict:
            return self.epic_cache_dict[ticker]
            
        # 2. Neon Global Map Hit
        conn = self.db._get_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT codice_capital_epic FROM capital_market_map WHERE UPPER(ticker_yahoo) = %s OR UPPER(ticker_binance) = %s LIMIT 1",
                        (ticker_upper, ticker_upper)
                    )
                    row = cur.fetchone()
                    if row:
                        epic = row[0]
                        self.epic_cache_dict[ticker] = epic
                        logger.info(f"🎯 [NEON MAP HIT] {ticker} -> {epic}")
                        return epic
            except Exception as e:
                logger.error(f"Errore query capital_market_map: {e}")
            finally:
                conn.close()

        # 3. Old Local DB Hit (Legacy Fallback)
        mapping = self.db.get_epic_mapping(ticker)
        if mapping:
            epic = mapping['epic_capital']
            self.epic_cache_dict[ticker] = epic
            return epic
            
        # 3. Broker API Search (Fallback)
        logger.info(f"🔎 Asset sconosciuto '{ticker}'. Avvio risoluzione dinamica API...")
        await self.authenticate_capital()
        
        headers = {
            "X-CAP-API-KEY": self.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.x_sec
        }
        
        clean_search = ticker.split(".")[0] # ES: ENEL.MI -> ENEL, AAPL -> AAPL (USA puro)
        url = f"{self.capital_base_url}/markets?searchTerm={clean_search}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        markets = data.get("markets", [])
                        
                        if not markets:
                            logger.warning(f"Nessun mercato trovato per {ticker} su Capital.com.")
                            return None
                            
                        # Isola e pulisci il dizionario dei simboli
                        raw_mapping = {m.get("instrumentName"): m.get("epic") for m in markets}
                        if isinstance(raw_mapping, dict):
                            market_names = {str(k): str(v) for k, v in raw_mapping.items() if k is not None and v is not None}
                        else:
                            market_names = {}
                        
                        # Cerchiamo un match esatto sul simbolo se possibile
                        for m in markets:
                            if m.get("epic", "").split("-")[0].upper() == clean_search.upper():
                                found_epic = m.get("epic")
                                instrument_name = m.get("instrumentName")
                                if ticker is None or found_epic is None or instrument_name is None:
                                    logger.warning(f"Mappatura fallita o incompleta per {ticker}. Salto la serializzazione.")
                                    return None
                                self.db.save_epic_mapping(ticker, found_epic, instrument_name)
                                self.epic_cache_dict[ticker] = found_epic
                                logger.info(f"✅ Match Simbolo trovato: {ticker} -> {found_epic}")
                                return found_epic
                        
                        # 4. Fuzzy Matching se non c'è match sul simbolo esatto
                        # Passiamo a rapidfuzz sul nome
                        choices = list(market_names.keys())
                        # Purtroppo non abbiamo il vero nome esteso da Yahoo qui, usiamo il ticker pulito o lo ricaviamo
                        # Simuliamo fuzzy match sul clean_search o sul ticker originale
                        best_match = process.extractOne(clean_search, choices, scorer=fuzz.ratio, score_cutoff=60)
                        # Nota: Lo score cutoff l'ho abbassato a 60 per ticker corti, idealmente se avessimo il nome societario useremmo 92
                        if best_match:
                            matched_name = best_match[0]
                            score = best_match[1]
                            found_epic = market_names[matched_name]
                            if score >= 92 or len(clean_search) < 5: # per ticker corti tolleriamo di più
                                if ticker is None or found_epic is None or matched_name is None:
                                    logger.warning(f"Mappatura fallita o incompleta per {ticker}. Salto la serializzazione.")
                                    return None
                                self.db.save_epic_mapping(ticker, found_epic, matched_name)
                                self.epic_cache_dict[ticker] = found_epic
                                logger.info(f"✅ Fuzzy Match ({score}%): {ticker} -> {found_epic} ({matched_name})")
                                return found_epic
                                
        except Exception as e:
            logger.error(f"Errore risoluzione dinamica API per {ticker}: {e}")
            
        return None
