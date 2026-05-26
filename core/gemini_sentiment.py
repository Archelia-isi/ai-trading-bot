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
                # Utilizziamo gemini-3.1-pro-preview per massima accuratezza analitica
                self.model = genai.GenerativeModel('gemini-3.1-pro-preview')
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
        Sei un analista quantitativo di un Hedge Fund speculativo ad alta frequenza (Day Trading).
        Analizza il sentiment e il potenziale speculativo odierno per l'asset: {asset_name}
        Considera le ultimissime notizie globali, i social media e l'hype del mercato.
        
        Devi restituire ESCLUSIVAMENTE un JSON valido con questa esatta struttura:
        {{
            "score": <intero da 0 a 100, dove 0 è panic selling estremo, 50 è neutro, 100 è buy speculativo assoluto>,
            "conviction": <intero da 1 a 10, dove 10 significa che la notizia è esplosiva e l'aumento/crollo è quasi certo oggi>,
            "leverage_multiplier": <intero da 1 a 10, che rappresenta la leva finanziaria consigliata. 10x per trade ultra sicuri, 1x se incerto>,
            "asset_risk": "<stringa 'HIGH' o 'LOW'. Usa 'HIGH' per crypto, meme stocks, small cap. Usa 'LOW' per indici, megacap tech, oro>",
            "motivazione": "<stringa breve che giustifica l'analisi speculativa per il day trading>"
        }}
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
