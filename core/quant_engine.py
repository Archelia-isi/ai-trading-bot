import logging
from core.capital_api import CapitalComAPI
from core.database import DatabaseManager

logger = logging.getLogger(__name__)

# Definizione dei profili dal file di specifiche del progetto
RISK_PROFILES = {
    "Il Pirata 🏴‍☠️": {"long_thresh": 65, "short_thresh": 35, "risk_pct": 0.05, "drawdown_max": 0.10},
    "Il Velocista ⚡": {"long_thresh": 70, "short_thresh": 30, "risk_pct": 0.03, "drawdown_max": 0.05},
    "Il Moderato 🛡️": {"long_thresh": 80, "short_thresh": 20, "risk_pct": 0.015, "drawdown_max": 0.03},
    "La Fortezza 🏰": {"long_thresh": 90, "short_thresh": 10, "risk_pct": 0.01, "drawdown_max": 0.015}
}

class QuantEngine:
    def __init__(self, api: CapitalComAPI, db: DatabaseManager):
        self.api = api
        self.db = db

    def evaluate_and_trade(self, asset: str, sentiment_score: int, profile_name: str, current_price: float):
        """
        Motore Quantitativo: incrocia lo score di sentiment di Gemini 
        con le soglie psicologiche del profilo di rischio scelto.
        """
        profile = RISK_PROFILES.get(profile_name)
        if not profile:
            logger.error(f"Profilo di rischio sconosciuto: {profile_name}")
            return None

        # Otteniamo il saldo reale/demo dal conto
        balance = self.api.get_account_balance()
        if balance <= 0:
            logger.warning("Saldo insufficiente. Impossibile procedere con il trade.")
            return None

        # Gestione Monetaria (Money Management): calcolo dimensione posizione
        size_eur = balance * profile["risk_pct"]
        size_qty = size_eur / current_price if current_price > 0 else 0

        action = None
        # Logica di Trading basata sulle soglie specificate per questo profilo
        if sentiment_score >= profile["long_thresh"]:
            action = "LONG"
            logger.info(f"🔥 SEGNALE FORTE LONG generato per {asset} (Score Gemini: {sentiment_score})")
        elif sentiment_score <= profile["short_thresh"]:
            action = "SHORT"
            logger.info(f"🩸 SEGNALE FORTE SHORT generato per {asset} (Score Gemini: {sentiment_score})")
        else:
            logger.info(f"⚖️ Nessun segnale per {asset} (Score {sentiment_score} è neutro per il profilo '{profile_name}')")
            return None

        # Simulazione ordine e log persistente nel Database
        self.db.log_trade(
            asset=asset,
            action=action,
            score=sentiment_score,
            risk_profile=profile_name,
            size=size_qty,
            price=current_price
        )
        
        return {
            "action": action,
            "asset": asset,
            "size_eur": size_eur,
            "size_qty": size_qty,
            "price": current_price
        }
