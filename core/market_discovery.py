import os
import json
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

class MarketDiscovery:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = None
        if self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                # Abilitiamo lo strumento di ricerca Google nativo
                self.model = genai.GenerativeModel(
                    'gemini-3.1-pro-preview',
                    tools='google_search_retrieval'
                )
                logger.info("Modulo Market Discovery inizializzato con Google Search Grounding.")
            except Exception as e:
                logger.error(f"Errore inizializzazione Discovery Model: {e}")

    def get_trending_assets(self, max_assets=2) -> list:
        """
        Interroga Gemini chiedendogli di scansionare il web e trovare gli asset più caldi.
        Restituisce una lista di nomi stringa.
        """
        if not self.model:
            logger.warning("Discovery Model non disponibile. Uso asset di fallback.")
            return ["Bitcoin", "Tesla"]
            
        prompt = f"""
        Scandaglia il web per le ultimissime notizie finanziarie in tempo reale a livello globale.
        Individua esattamente {max_assets} asset finanziari (azioni, criptovalute, materie prime) che sono attualmente 
        sotto i riflettori a causa di notizie fresche e dirompenti (es. tweet di Elon Musk, IPO, scandali, trimestrali, crisi politiche).
        Devi restituire ESCLUSIVAMENTE un array JSON valido contenente solo i nomi comuni di questi asset in inglese o italiano.
        Non aggiungere alcun testo prima o dopo l'array JSON, non usare formattazione markdown.
        Esempio: ["Tesla", "Bitcoin"]
        """
        
        try:
            logger.info("🌍 Avvio scansione web globale per ricerca asset caldi...")
            response = self.model.generate_content(prompt)
            text = response.text.strip()
            
            # Pulizia per sicurezza se Gemini aggiunge markdown
            if text.startswith("```json"):
                text = text.replace("```json", "").replace("```", "").strip()
            elif text.startswith("```"):
                text = text.replace("```", "").strip()
                
            assets = json.loads(text)
            if isinstance(assets, list) and len(assets) > 0:
                logger.info(f"🎯 Asset scoperti dalle news: {assets}")
                return assets
            else:
                logger.warning("Formato JSON inatteso. Uso fallback.")
                return ["Bitcoin", "Tesla"]
                
        except Exception as e:
            logger.error(f"Errore durante il Market Discovery (Possibile rate limit o API error): {e}")
            return ["Bitcoin", "Tesla"]
