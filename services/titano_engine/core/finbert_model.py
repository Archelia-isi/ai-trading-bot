import logging
import os
import requests

logger = logging.getLogger(__name__)

class FinBERTModel:
    def __init__(self):
        self.api_url = os.getenv("NLP_SERVICE_URL", "http://localhost:8000")
        logger.info(f"FinBERT connesso al microservizio NLP: {self.api_url}")

    def analyze_news_sentiment(self, text: str) -> dict:
        """
        Analizza un testo finanziario tramite il Microservizio NLP.
        Ritorna un dizionario es. {'label': 'POSITIVE', 'score': 0.95}
        """
        try:
            max_len = 500
            safe_text = text[:max_len] if len(text) > max_len else text
            
            res = requests.post(f"{self.api_url}/analyze", json={"text": safe_text}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"label": data.get("label", "NEUTRAL").lower(), "score": data.get("score", 0.5)}
            else:
                logger.warning(f"Errore dal server NLP: {res.status_code}")
                return {"label": "neutral", "score": 0.5}
        except Exception as e:
            logger.error(f"Errore di rete verso il server NLP: {e}")
            return {"label": "neutral", "score": 0.5}
