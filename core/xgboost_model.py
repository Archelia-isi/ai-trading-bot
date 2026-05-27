import logging
import os
import requests
from core.capital_api import CapitalComAPI

logger = logging.getLogger(__name__)

class XGBoostEngine:
    def __init__(self):
        self.api_url = os.getenv("MATH_SERVICE_URL", "http://localhost:8001")
        logger.info(f"Modulo XGBoost inizializzato (Connesso al Microservizio Math: {self.api_url}).")

    def calculate_probability(self, epic: str, capital_api: CapitalComAPI) -> float:
        """
        Scarica 1 anno di storico tramite Capital.com API, lo invia al Microservizio XGBoost
        e restituisce la probabilità (0-1) di una candela verde imminente.
        """
        try:
            logger.info(f"XGBoost: Download dati storici (250gg) per EPIC '{epic}' da Capital.com...")
            
            url = f"{capital_api.base_url}/prices/{epic}?resolution=DAY&max=250"
            res = capital_api._requests_get(url)
            
            if not res or res.status_code != 200:
                logger.error(f"XGBoost: Impossibile scaricare storico da Capital.com per {epic}")
                return 0.5
                
            prices_data = res.json().get('prices', [])
            
            # Inviamo i dati al microservizio matematico
            payload = {
                "prices": prices_data,
                "epic": epic
            }
            
            logger.info(f"XGBoost: Invio dati al Microservizio Math per elaborazione...")
            api_res = requests.post(f"{self.api_url}/predict", json=payload, timeout=15)
            
            if api_res.status_code == 200:
                data = api_res.json()
                prob = data.get("probability", 0.5)
                return float(prob)
            else:
                logger.warning(f"Errore dal server Math: {api_res.status_code} - {api_res.text}")
                return 0.5
            
        except Exception as e:
            logger.error(f"Errore di rete verso il server Math per {epic}: {e}")
            return 0.5
