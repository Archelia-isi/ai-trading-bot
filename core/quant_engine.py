import logging
from core.capital_api import CapitalComAPI
from core.database import DatabaseManager

logger = logging.getLogger(__name__)

# Definizione dei profili: ogni profilo ha soglie di segnale e moltiplicatori in base al rischio dell'asset
RISK_PROFILES = {
    "La Fortezza 🏰": {"long_thresh": 85, "short_thresh": 15, "multi_low": 1.0, "multi_high": 0.2},
    "Il Moderato 🛡️": {"long_thresh": 75, "short_thresh": 25, "multi_low": 1.5, "multi_high": 0.5},
    "Il Velocista ⚡": {"long_thresh": 65, "short_thresh": 35, "multi_low": 1.0, "multi_high": 1.5},
    "Il Pirata 🏴‍☠️": {"long_thresh": 55, "short_thresh": 45, "multi_low": 0.5, "multi_high": 3.0}
}

class QuantEngine:
    def __init__(self, api: CapitalComAPI, db: DatabaseManager):
        self.api = api
        self.db = db

    def evaluate_and_trade(self, asset: str, sentiment_data: dict, profile_name: str, current_price: float):
        """
        Motore Quantitativo: incrocia i dati dinamici di Gemini (score, conviction, asset_risk)
        con le regole di speculazione del profilo.
        """
        profile = RISK_PROFILES.get(profile_name)
        if not profile:
            logger.error(f"Profilo di rischio sconosciuto: {profile_name}")
            return None

        sentiment_score = sentiment_data.get("score", 50)
        conviction = sentiment_data.get("conviction", 1)
        asset_risk = sentiment_data.get("asset_risk", "LOW").upper()
        
        leverage = sentiment_data.get("leverage_multiplier", 1)
        
        # Logica di Trading (Segnale)
        action = None
        if sentiment_score >= profile["long_thresh"]:
            action = "LONG"
        elif sentiment_score <= profile["short_thresh"]:
            action = "SHORT"
        else:
            logger.info(f"⚖️ Nessun segnale forte per {asset} (Score: {sentiment_score})")
            return None

        # Sizing Dinamico: Base = 0.5% * Conviction (da 1 a 10) -> max 5% base (Margine)
        base_pct = (conviction * 0.5) / 100.0
        
        # Moltiplicatore di Profilo in base al Rischio Intrinseco
        multiplier = profile["multi_high"] if asset_risk == "HIGH" else profile["multi_low"]
        margin_pct = base_pct * multiplier
        margin_pct = min(margin_pct, 0.20) # Max 20% margin per trade

        balance = self.api.get_account_balance()
        if balance <= 0:
            logger.warning("Saldo insufficiente.")
            return None

        # Margine in EUR bloccato dal conto
        margin_eur = balance * margin_pct
        
        # Size reale a mercato usando la leva dell'AI
        notional_eur = margin_eur * leverage
        size_qty = notional_eur / current_price if current_price > 0 else 0
        
        # Logiche Scalping / Day Trading (Distanza Stop Loss Dinamico)
        # Non impostiamo un TP per lasciar correre (Trailing Stop gestito da app.py)
        sl_distance = 0.05 if asset_risk == "HIGH" else 0.02

        logger.info(f"🔥 SEGNALE {action} {asset} | Conviction: {conviction} | Rischio: {asset_risk} | Leva: {leverage}x | Size: €{notional_eur:.2f} (Margine: €{margin_eur:.2f})")

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
            "margin_eur": margin_eur,
            "notional_eur": notional_eur,
            "leverage": leverage,
            "size_qty": size_qty,
            "entry_price": current_price,
            "sl_distance": sl_distance,
            "conviction": conviction
        }
