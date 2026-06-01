import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str) -> bool:
        """Invia un messaggio testuale (in italiano) all'utente via Telegram."""
        if not self.token or not self.chat_id or "inserisci_qui" in self.token:
            logger.warning(f"[TELEGRAM SIMULATO] Messaggio: {text}")
            return False
            
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Messaggio Telegram inviato con successo all'utente.")
                return True
            else:
                logger.error(f"Errore invio Telegram (Code {response.status_code}): {response.text}")
                return False
        except Exception as e:
            logger.error(f"Eccezione durante l'invio Telegram: {e}")
            return False

    def send_trade_alert(self, asset: str, profile: str, action: str, price: float):
        """Allarme standard per un'esecuzione."""
        msg = (
            f"📈 <b>OPERAZIONE ESEGUITA</b>\n\n"
            f"<b>Asset:</b> {asset}\n"
            f"<b>Azione:</b> {action}\n"
            f"<b>Prezzo:</b> {price} €\n"
            f"<b>Profilo:</b> {profile}\n\n"
            f"<i>Azione simulata (Fase 3) - Salvata nel Database.</i>"
        )
        return self.send_message(msg)

    def send_kill_switch_alert(self):
        """Allarme di emergenza per disconnessione o stop manuale."""
        msg = (
            "🚨 <b>KILL SWITCH ATTIVATO MANUALMENTE!</b> 🚨\n\n"
            "Ho forzato la chiusura di tutte le posizioni a mercato (Simulazione). "
            "Il bot è ora in stato di ARRESTO DI SICUREZZA."
        )
        return self.send_message(msg)

    def send_drawdown_alert(self):
        """Allarme di superamento Drawdown (Perdita Massima)."""
        msg = (
            "⚠️ <b>ALLARME CRITICO DRAWDOWN</b> ⚠️\n\n"
            "Il limite di perdita massimo consentito dal tuo profilo è stato superato. "
            "Ho arrestato il bot automaticamente per preservare il capitale residuo."
        )
        return self.send_message(msg)
