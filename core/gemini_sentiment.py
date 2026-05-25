import os
import json
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configurazione Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GeminiSentimentAnalyzer:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key or "inserisci_qui" in self.api_key:
            logger.warning("ATTENZIONE: GEMINI_API_KEY non trovata o non valida. Modalità MOCK (Simulazione) attiva.")
            self.model = None
        else:
            try:
                genai.configure(api_key=self.api_key)
                # Utilizziamo gemini-1.5-flash per massima velocità (ideale per trading)
                self.model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("Modulo Gemini inizializzato correttamente.")
            except Exception as e:
                logger.error(f"Errore inizializzazione Gemini: {e}")
                self.model = None

    def analyze_market_sentiment(self, asset_name: str, news_context: str = "") -> dict:
        """
        Analizza il sentiment di un asset tramite Gemini e restituisce uno score da 1 a 100.
        """
        if self.model is None:
            logger.info(f"Esecuzione analisi sentiment simulata per {asset_name} (chiave mancante).")
            return {"score": 50, "motivazione": "API Key mancante, restituito valore neutrale simulato (50)."}

        prompt = f"""
        Sei un esperto analista finanziario quantitativo.
        Il tuo compito è analizzare il sentiment di mercato per l'asset: {asset_name}.
        Contesto di mercato/Notizie: {news_context if news_context else "Nessuna notizia rilevante fornita. Basati sullo storico recente noto."}
        
        REGOLE FONDAMENTALI:
        1. Valuta il sentiment da 1 a 100 (dove 1 è panico/short forte e 100 è euforia/long forte).
        2. Rispondi SEMPRE E SOLO IN LINGUA ITALIANA.
        3. Restituisci ESCLUSIVAMENTE un oggetto JSON valido con questa struttura esatta:
        {{
            "score": <numero da 1 a 100>,
            "motivazione": "<breve motivazione tecnica in italiano (max 20 parole)>"
        }}
        Niente markdown intorno al JSON, solo il testo JSON crudo.
        """
        
        try:
            logger.info(f"Richiesta analisi sentiment per {asset_name} inviata a Gemini...")
            response = self.model.generate_content(prompt)
            testo = response.text.strip()
            
            # Pulizia per evitare errori di parsing se Gemini inserisce formattazione markdown
            if testo.startswith("```json"):
                testo = testo[7:-3]
            elif testo.startswith("```"):
                testo = testo[3:-3]
                
            risultato = json.loads(testo.strip())
            logger.info(f"✅ Sentiment ricevuto per {asset_name}: Score {risultato.get('score')}")
            return risultato
            
        except json.JSONDecodeError:
            logger.error(f"Errore di parsing JSON dalla risposta di Gemini. Testo grezzo: {testo}")
            return {"score": 50, "motivazione": "Errore tecnico: parsing JSON fallito. Operazione annullata."}
        except Exception as e:
            logger.error(f"Errore critico durante la comunicazione con Gemini: {str(e)}")
            return {"score": 50, "motivazione": f"Timeout o errore di connessione con le API."}
