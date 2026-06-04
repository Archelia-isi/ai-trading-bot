import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class CapitalComAPI:
    def __init__(self):
        self.api_key = os.getenv("CAPITAL_API_KEY")
        self.api_secret = os.getenv("CAPITAL_API_SECRET")
        self.email = os.getenv("CAPITAL_EMAIL")
        self.base_url = "https://demo-api-capital.backend-capital.com/api/v1"
        self.cst_token = None
        self.x_security_token = None
        self.is_authenticated = False
        self.market_hours_cache = {}

    def _get_headers(self, with_auth=False):
        headers = {'Content-Type': 'application/json', 'X-CAP-API-KEY': str(self.api_key)}
        if with_auth and self.cst_token and self.x_security_token:
            headers['CST'] = self.cst_token
            headers['X-SECURITY-TOKEN'] = self.x_security_token
        return headers

    def authenticate(self) -> bool:
        """Autenticazione all'API di Capital.com per ottenere i token di sessione."""
        if not self.api_key or not self.api_secret or not self.email:
            logger.warning("Chiavi Capital.com non complete in .env. Utilizzo modalità simulata (Mock).")
            self.is_authenticated = False
            return False
            
        try:
            logger.info("Tentativo di connessione a Capital.com (Demo)...")
            payload = {
                "identifier": self.email,
                "password": self.api_secret,
                "encryptedPassword": False
            }
            response = requests.post(f"{self.base_url}/session", json=payload, headers=self._get_headers(), timeout=10)
            
            if response.status_code == 200:
                self.cst_token = response.headers.get('CST')
                self.x_security_token = response.headers.get('X-SECURITY-TOKEN')
                if self.cst_token and self.x_security_token:
                    logger.info("✅ Connessione a Capital.com stabilita! Token salvati.")
                    self.is_authenticated = True
                    return True
                else:
                    logger.error("Login riuscito ma token CST/X-SECURITY-TOKEN mancanti negli header della risposta.")
                    return False
            else:
                logger.error(f"Errore di connessione a Capital.com (Code: {response.status_code}): {response.text}")
                return False
        except Exception as e:
            logger.error(f"Eccezione durante la connessione a Capital.com: {e}")
            return False

    def get_account_balance(self) -> float:
        """Recupera il saldo del conto Demo. Restituisce un valore fittizio se in modalità MOCK."""
        if not self.is_authenticated:
            return 0.00 # Saldo fittizio per poter sviluppare la UI se mock attivo
            
        try:
            response = requests.get(f"{self.base_url}/accounts", headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                accounts = data.get('accounts', [])
                if accounts:
                    # Di solito il primo account è quello primario, oppure filtriamo per status="ENABLED"
                    balance = accounts[0].get('balance', {}).get('balance', 0.0)
                    return float(balance)
            logger.error(f"Impossibile recuperare il saldo, risposta: {response.text}")
            return 0.0
        except Exception as e:
            logger.error(f"Errore nel recupero saldo Capital.com: {e}")
            return 0.0

    def get_all_positions(self) -> list:
        """Recupera la lista cruda di tutte le posizioni aperte su Capital.com."""
        if not self.is_authenticated:
            return []
        try:
            response = requests.get(f"{self.base_url}/positions", headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get('positions', [])
            return []
        except Exception as e:
            logger.error(f"Errore nel recupero posizioni: {e}")
            return []

    def get_margin_info(self) -> dict:
        """Restituisce equity e margine disponibile per calcolare l'esposizione."""
        if not self.is_authenticated:
            return {"equity": 0.0, "available": 0.0}
        try:
            response = requests.get(f"{self.base_url}/accounts", headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                accounts = response.json().get('accounts', [])
                if accounts:
                    return {
                        "equity": float(bal.get('balance', 0.0)),
                        "available": float(bal.get('available', 0.0)),
                        "margin": float(bal.get('balance', 0.0)) - float(bal.get('available', 0.0))
                    }
            return {"equity": 0.0, "available": 0.0, "margin": 0.0}
        except:
            return {"equity": 0.0, "available": 0.0}

    def get_historical_prices(self, epic: str, hours: int = 24) -> list:
        """Recupera le ultime N candele orarie per l'analisi quantitativa dell'AI."""
        if not self.is_authenticated:
            return []
        try:
            url = f"{self.base_url}/prices/{epic}?resolution=HOUR&max={hours}"
            response = requests.get(url, headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                return response.json().get('prices', [])
            return []
        except:
            return []

    def search_instrument(self, search_term: str):
        """Cerca un EPIC (simbolo) su Capital.com partendo da un nome comune."""
        if not self.is_authenticated:
            return None
            
        try:
            url = f"{self.base_url}/markets?searchTerm={search_term}"
            response = requests.get(url, headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                markets = data.get('markets', [])
                if markets:
                    # Ritorna il primo risultato utile
                    for m in markets:
                        if m.get('marketState') == 'TRADEABLE':
                            return {
                                "epic": m.get('epic'),
                                "name": m.get('instrumentName')
                            }
                    return {
                        "epic": markets[0].get('epic'),
                        "name": markets[0].get('instrumentName')
                    }
            return None
        except Exception as e:
            logger.error(f"Errore ricerca strumento su Capital.com: {e}")
            return None
            
    def get_market_price(self, epic: str) -> float:
        """Ottiene il prezzo attuale di un EPIC specifico."""
        if not self.is_authenticated:
            return round(float(len(epic) * 10), 2) # Prezzo finto per test UI
        try:
            url = f"{self.base_url}/markets/{epic}"
            response = requests.get(url, headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                snapshot = data.get('snapshot', {})
                bid = snapshot.get('bid')
                offer = snapshot.get('offer')
                if bid and offer:
                    return round((bid + offer) / 2, 4)
            return 100.0
        except:
            return 100.0

    def get_min_deal_size(self, epic: str) -> float:
        """Cerca la size minima consentita per un EPIC per evitare rigetti dal broker."""
        if not self.is_authenticated:
            return 0.1
        try:
            url = f"{self.base_url}/markets/{epic}"
            response = requests.get(url, headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                return float(data.get('dealingRules', {}).get('minDealSize', {}).get('value', 0.1))
            return 0.1
        except:
            return 0.1

    def place_order(self, epic: str, direction: str, size: float) -> dict:
        """Piazza un ordine di mercato reale su Capital.com."""
        if not self.is_authenticated:
            logger.info(f"[MOCK] Ordine piazzato: {direction} {epic} size {size}")
            return {"status": "success", "dealId": "mock_deal_id"}
            
        try:
            min_size = self.get_min_deal_size(epic)
            if size < min_size:
                logger.warning(f"Size calcolata ({size}) inferiore al minimo del broker ({min_size}). Arrotondo al minimo se l'AI ha conviction!")
                size = min_size
            api_dir = "BUY" if direction.upper() in ["LONG", "BUY"] else "SELL"
            
            payload = {
                "epic": epic,
                "direction": api_dir,
                "size": round(size, 4),
                "guaranteedStop": False
            }
            response = requests.post(f"{self.base_url}/positions", json=payload, headers=self._get_headers(with_auth=True), timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"✅ Ordine Capital.com Accettato! {direction} {epic}")
                return {"status": "success", "dealReference": data.get('dealReference')}
            else:
                logger.error(f"❌ Ordine Capital.com Rifiutato: {response.text}")
                return {"status": "error", "message": response.text}
        except Exception as e:
            logger.error(f"Errore piazzamento ordine: {e}")
            return {"status": "error", "message": str(e)}

    def close_position_by_epic(self, epic: str):
        """Chiude tutte le posizioni aperte per un dato epic (utile per Trailing Stop)."""
        if not self.is_authenticated:
            logger.info(f"[MOCK] Posizione chiusa per {epic}")
            return True
            
        try:
            # 1. Recupero tutte le posizioni aperte per trovare i dealId associati a questo EPIC
            response = requests.get(f"{self.base_url}/positions", headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                positions = response.json().get('positions', [])
                closed_any = False
                for p in positions:
                    market = p.get('market', {})
                    if market.get('epic') == epic:
                        deal_id = p.get('position', {}).get('dealId')
                        if deal_id:
                            # 2. Chiudo il deal specifico
                            del_resp = requests.delete(f"{self.base_url}/positions/{deal_id}", headers=self._get_headers(with_auth=True), timeout=10)
                            if del_resp.status_code == 200:
                                logger.info(f"✅ Posizione chiusa con successo per {epic} (DealID: {deal_id})")
                                closed_any = True
                            else:
                                logger.error(f"❌ Errore chiusura posizione {deal_id}: {del_resp.text}")
                return closed_any
            return False
        except Exception as e:
            logger.error(f"Errore durante la chiusura posizioni per {epic}: {e}")
            return False

    def close_position_by_deal_id(self, deal_id: str) -> bool:
        """Chiude una posizione specifica bypassando il check dell'epic (Evita Rate Limit)."""
        if not self.is_authenticated:
            return True
        try:
            del_resp = requests.delete(f"{self.base_url}/positions/{deal_id}", headers=self._get_headers(with_auth=True), timeout=10)
            if del_resp.status_code == 200:
                logger.info(f"✅ Posizione {deal_id} chiusa con successo.")
                return True
            else:
                logger.error(f"❌ Errore chiusura posizione {deal_id}: {del_resp.text}")
                return False
        except Exception as e:
            logger.error(f"Errore: {e}")
            return False

    def get_market_hours(self, epic: str) -> dict:
        """Scarica e salva in cache gli orari di apertura per un epic."""
        if not self.is_authenticated:
            return {}
            
        if epic in self.market_hours_cache:
            return self.market_hours_cache[epic]
            
        try:
            url = f"{self.base_url}/markets/{epic}"
            response = requests.get(url, headers=self._get_headers(with_auth=True), timeout=10)
            if response.status_code == 200:
                data = response.json()
                hours = data.get('instrument', {}).get('openingHours', {})
                self.market_hours_cache[epic] = hours
                return hours
            return {}
        except Exception as e:
            logger.error(f"Errore recupero market hours per {epic}: {e}")
            return {}

    def is_market_closing_soon(self, epic: str, threshold_minutes: int = 15) -> bool:
        """Verifica se il mercato per l'epic specificato sta chiudendo entro i prossimi X minuti."""
        hours = self.get_market_hours(epic)
        if not hours:
            return False
            
        from datetime import datetime
        import pytz
        
        now_utc = datetime.now(pytz.utc)
        day_str = now_utc.strftime('%a').lower() # mon, tue, wed...
        
        hours_today = hours.get(day_str, [])
        if not hours_today:
            return False
            
        for period in hours_today:
            try:
                # Esempio: "08:00 - 21:00" o "08:00 - 00:00"
                start_str, end_str = period.split(" - ")
                
                end_time = datetime.strptime(end_str, "%H:%M").time()
                if end_str == "00:00":
                    end_time = datetime.strptime("23:59", "%H:%M").time()
                    
                end_dt = datetime.combine(now_utc.date(), end_time).replace(tzinfo=pytz.utc)
                
                time_to_close = (end_dt - now_utc).total_seconds() / 60.0
                
                # Se mancano tra 0 e threshold_minutes
                if 0 < time_to_close <= threshold_minutes:
                    return True
            except Exception as e:
                continue
                
        return False
