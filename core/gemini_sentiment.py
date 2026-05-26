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

    def analyze_market_sentiment(self, asset_name: str, historical_data: list = None) -> dict:
        """
        Analizza il sentiment di un asset tramite Gemini, incrociandolo con la price action storica.
        """
        if self.model is None:
            logger.info(f"Esecuzione analisi sentiment simulata per {asset_name} (chiave mancante).")
            return {"score": 50, "conviction": 1, "allocation_percentage": 5, "asset_risk": "LOW", "motivazione": "Mock"}

        # Formatta lo storico dei prezzi in modo leggibile per l'LLM
        history_str = "Dati storici non disponibili."
        if historical_data:
            lines = []
            for h in historical_data[-12:]: # Mostriamo le ultime 12 ore per non saturare il prompt
                time = h.get('snapshotTimeUTC')
                op = h.get('openPrice', {}).get('bid', 0)
                cp = h.get('closePrice', {}).get('bid', 0)
                hp = h.get('highPrice', {}).get('bid', 0)
                lp = h.get('lowPrice', {}).get('bid', 0)
                lines.append(f"[{time}] Open:{op} High:{hp} Low:{lp} Close:{cp}")
            history_str = "\n".join(lines)

        prompt = f"""
        Sei un Analista Quantitativo Elite di un Hedge Fund ad alta frequenza.
        Devi decidere se investire sull'asset: {asset_name}
        
        DATI STORICI (Ultime 12 Ore - Candele Orarie UTC):
        {history_str}
        
        ATTIVITA' RICHIESTA:
        1. Usa lo strumento Google Search per trovare le ultimissime news su questo asset.
        2. Confronta le news appena uscite con l'andamento del prezzo storico fornito sopra. 
           (Es: La news è ottima, ma il prezzo è già salito troppo nelle ultime ore? Allora il trend è vecchio, scartalo. 
           La news è ottima e il prezzo sta appena curvando al rialzo? Compralo).
        3. Decidi l'esatta percentuale di capitale da allocare per questo trade in base alla solidità dell'analisi.
        
        Devi restituire ESCLUSIVAMENTE un JSON valido con questa esatta struttura:
        {{
            "score": <intero da 0 a 100, dove 0 è sell forte, 50 neutro, 100 è buy speculativo assoluto>,
            "conviction": <intero da 1 a 10, dove 10 significa che il setup news+grafico è perfetto>,
            "allocation_percentage": <intero da 1 a 20, rappresenta la % di portafoglio da investire su questo singolo trade>,
            "asset_risk": "<stringa 'HIGH' o 'LOW'. Usa 'HIGH' per crypto/meme, 'LOW' per indici/megacap>",
            "motivazione": "<stringa breve che giustifica l'analisi speculativa incrociando news e grafico>"
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
