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
        self.base_url = "https://demo-api-capital.com/api/v1"
        self.cst_token = None
        self.x_security_token = None
        self.is_authenticated = False

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
                "password": self.api_secret
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
            return 10000.00 # Saldo fittizio per poter sviluppare la UI se mock attivo
            
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
