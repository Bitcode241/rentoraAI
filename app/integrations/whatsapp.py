"""WhatsApp Cloud API integration (send + webhook ready)."""
import httpx
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("whatsapp")


class WhatsAppService:
    def __init__(self):
        self.enabled = bool(settings.whatsapp_token and settings.whatsapp_phone_id)

    def send(self, to_phone: str, body: str) -> str:
        if not self.enabled:
            log.info("whatsapp_send_simulated", to=to_phone)
            return "simulated"
        url = f"https://graph.facebook.com/v19.0/{settings.whatsapp_phone_id}/messages"
        headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": body},
        }
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=15)
            r.raise_for_status()
            return r.json().get("messages", [{}])[0].get("id", "")
        except Exception as e:  # pragma: no cover
            log.warning("whatsapp_send_failed", error=str(e))
            return ""


whatsapp_service = WhatsAppService()
