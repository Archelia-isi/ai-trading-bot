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

    def analyze_market_sentiment(self, asset_name: str, historical_data: list = None, finbert_data: dict = None, xgboost_prob: float = None) -> dict:
        """
        Analizza il sentiment finale incrociando FinBERT, XGBoost, Price Action e Web Search.
        """
        if self.model is None:
            logger.info(f"Esecuzione analisi sentiment simulata per {asset_name} (chiave mancante).")
            return {"score": 50, "conviction": 1, "allocation_percentage": 5, "leverage_multiplier": 1, "asset_risk": "LOW", "motivazione": "Mock"}

        history_str = "Dati storici non disponibili."
        if historical_data:
            lines = []
            for h in historical_data[-12:]:
                time = h.get('snapshotTimeUTC')
                op = h.get('openPrice', {}).get('bid', 0)
                cp = h.get('closePrice', {}).get('bid', 0)
                hp = h.get('highPrice', {}).get('bid', 0)
                lp = h.get('lowPrice', {}).get('bid', 0)
                lines.append(f"[{time}] Open:{op} High:{hp} Low:{lp} Close:{cp}")
            history_str = "\n".join(lines)
            
        finbert_str = f"Label: {finbert_data.get('label', 'unknown')} | Confidence: {finbert_data.get('score', 0):.2f}" if finbert_data else "Nessun dato FinBERT."
        xgb_str = f"{xgboost_prob * 100:.1f}% di probabilità statistica di rialzo oggi" if xgboost_prob is not None else "Nessun dato XGBoost."

        prompt = f"""
        Sei il Comitato d'Investimento (Analista Elite) di un Hedge Fund.
        Devi deliberare l'investimento sull'asset: {asset_name}
        
        REPORT DEI SUB-MODELLI AI:
        1. FinBERT (Sentiment NLP su News Headline): {finbert_str}
        2. XGBoost (Modello Matematico su Storico 1 Anno): {xgb_str}
        
        DATI STORICI RECENTI (Ultime 12 Ore - Candele UTC):
        {history_str}
        
        ATTIVITA' RICHIESTA:
        1. Usa Google Search se ritieni di dover approfondire la motivazione del Sentiment di FinBERT.
        2. Pesa matematicamente il risultato di XGBoost (se > 50% è bullish tecnicamente) con il momentum delle news.
        3. Decidi l'esatta percentuale di capitale da allocare.
        4. Decidi il Moltiplicatore di Leva Finanziaria (da 1 a 10). Se FinBERT e XGBoost sono fortemente in accordo su un asset a bassa volatilità (es. indici), usa leva alta. Altrimenti leva bassa.
        
        Restituisci ESCLUSIVAMENTE un JSON valido con questa struttura:
        {{
            "score": <0-100, dove 100 è buy estremo>,
            "conviction": <1-10>,
            "allocation_percentage": <1-30, % portafoglio>,
            "leverage_multiplier": <1-10, leva da applicare al broker>,
            "asset_risk": "<HIGH o LOW>",
            "motivazione": "<Breve giustificazione che cita FinBERT e XGBoost>"
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
