import logging
from transformers import pipeline

logger = logging.getLogger(__name__)

class FinBERTModel:
    def __init__(self):
        logger.info("Avvio inizializzazione FinBERT (potrebbe richiedere il download la prima volta)...")
        try:
            # Carichiamo la pipeline di sentiment analysis specifica per testi finanziari
            self.nlp = pipeline("sentiment-analysis", model="ProsusAI/finbert")
            logger.info("✅ Modello FinBERT caricato con successo in memoria.")
        except Exception as e:
            logger.error(f"Errore caricamento FinBERT: {e}")
            self.nlp = None

    def analyze_news_sentiment(self, text: str) -> dict:
        """
        Analizza un testo finanziario con FinBERT.
        Ritorna un dizionario es. {'label': 'positive', 'score': 0.95}
        """
        if not self.nlp:
            logger.warning("FinBERT non disponibile, restituisco neutro.")
            return {"label": "neutral", "score": 0.5}
            
        try:
            # FinBERT ha un limite di token (512). Tagliamo il testo se è troppo lungo.
            max_len = 500
            safe_text = text[:max_len] if len(text) > max_len else text
            
            result = self.nlp(safe_text)[0]
            # label sarà 'positive', 'negative' o 'neutral'
            return result
        except Exception as e:
            logger.error(f"Errore esecuzione FinBERT: {e}")
            return {"label": "neutral", "score": 0.5}
