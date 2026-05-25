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
        # URL base per l'ambiente DEMO di Capital.com
        self.base_url = "https://demo-api-capital.com/api/v1"
        self.cst_token = None
        self.x_security_token = None
        self.is_authenticated = False

    def _get_headers(self):
        headers = {'Content-Type': 'application/json', 'X-CAP-API-KEY': str(self.api_key)}
        if self.cst_token and self.x_security_token:
            headers['CST'] = self.cst_token
            headers['X-SECURITY-TOKEN'] = self.x_security_token
        return headers

    def authenticate(self) -> bool:
        """Autenticazione all'API di Capital.com per ottenere i token di sessione."""
        if not self.api_key or "inserisci_qui" in self.api_key:
            logger.warning("Chiavi Capital.com non configurate in .env. Utilizzo modalità simulata (Mock).")
            self.is_authenticated = False
            return False
            
        try:
            logger.info("Tentativo di connessione a Capital.com (Demo)...")
            # Logica di autenticazione placeholder (necessita del body corretto in base a identifier/password)
            # In questo modulo verificheremo se le chiavi rispondono ad un ping
            response = requests.get(f"{self.base_url}/ping", headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                logger.info("✅ Connessione a Capital.com stabilita con successo!")
                self.is_authenticated = True
                return True
            else:
                logger.error(f"Errore di connessione a Capital.com: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Eccezione durante la connessione a Capital.com: {e}")
            return False

    def get_account_balance(self) -> float:
        """Recupera il saldo del conto Demo. Restituisce un valore fittizio se in modalità MOCK."""
        if not self.is_authenticated:
            return 10000.00 # Saldo fittizio per poter sviluppare la UI
            
        try:
            response = requests.get(f"{self.base_url}/accounts", headers=self._get_headers(), timeout=10)
            if response.status_code == 200:
                data = response.json()
                balance = data.get('accounts', [{}])[0].get('balance', {}).get('balance', 0.0)
                return float(balance)
            return 0.0
        except Exception as e:
            logger.error(f"Errore nel recupero saldo Capital.com: {e}")
            return 0.0
