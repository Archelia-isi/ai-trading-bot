import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

class MarketDiscovery:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if self.api_key:
            logger.info("Modulo Market Discovery inizializzato (REST API Mode per Google Search).")
        else:
            logger.error("Nessuna API Key fornita per Market Discovery.")

    def get_trending_assets(self) -> list:
        """
        Interroga Gemini chiedendogli di scansionare il web e trovare tutti gli asset più caldi.
        Restituisce una lista di nomi stringa.
        """
        if not self.api_key:
            logger.warning("Discovery Model non disponibile (No API Key). Uso asset di fallback.")
            return ["Bitcoin", "Tesla"]
            
        prompt = """
        Scandaglia il web per le ultimissime notizie finanziarie in tempo reale a livello globale.
        Il tuo compito è individuare TUTTI gli asset finanziari (azioni, criptovalute, materie prime, forex) che sono
        attualmente al centro di "Catalizzatori Istituzionali" estremamente potenti e verificati.
        
        REGOLE FERREE:
        1. NON C'È ALCUN LIMITE NUMERICO: se ci sono 20 asset eccezionali, restituiscili tutti. Se ce ne sono 0, restituisci un array vuoto [].
        2. FILTRO QUALITATIVO ESTREMO: Scarta categoricamente rumors, speculazioni deboli, hype passeggero su social media e notizie già scontate dal mercato.
        3. Cerca SOLO: Trimestrali clamorose (sorprese assolute), acquisizioni o fusioni milionarie, rivoluzioni tecnologiche confermate, shock macroeconomici o geopolitici severi, breakout storici certificati.
        
        Devi restituire ESCLUSIVAMENTE un array JSON valido contenente solo i nomi comuni di questi asset in inglese o italiano.
        Non aggiungere alcun testo prima o dopo l'array JSON.
        Esempio: ["Tesla", "NVIDIA", "Oro", "Bitcoin", "Apple"]
        """
        
        try:
            logger.info("🌍 Avvio scansione web globale per ricerca asset caldi (via REST API)...")
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={self.api_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"googleSearch": {}}]
            }
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            
            if response.status_code == 200:
                data = response.json()
                text = data['candidates'][0]['content']['parts'][0]['text'].strip()
                
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
            else:
                logger.error(f"Errore REST API Gemini: {response.text}")
                return ["Bitcoin", "Tesla"]
                
        except Exception as e:
            logger.error(f"Errore critico durante il Market Discovery (Possibile rate limit o crash REST API): {e}")
            return ["Bitcoin", "Tesla"]
