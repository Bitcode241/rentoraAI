"""Unified email facade.

Chooses the best available provider:
  1. IMAP/SMTP (mailcow / custom domain / Gmail-via-IMAP)  -> if configured
  2. Gmail API                                             -> if Google creds exist
  3. Simulation (logs only)                                -> otherwise

The rest of the app imports `email_service` and never cares which is active.
"""
from app.core.logging import get_logger
from app.integrations.email_imap import imap_smtp_service

log = get_logger("email-service")


class _SimulationEmail:
    enabled = False

    def list_unread(self, max_results: int = 10):
        return []

    def send(self, to, subject, body, thread_id=""):
        log.info("email_send_simulated", to=to, subject=subject)
        return "simulated"

    def mark_read(self, message_id):
        return None


def _select_provider():
    if imap_smtp_service.enabled:
        log.info("email_provider_selected", provider="imap_smtp")
        return imap_smtp_service
    try:
        from app.integrations.gmail import gmail_service
        if gmail_service.enabled:
            log.info("email_provider_selected", provider="gmail_api")
            return gmail_service
    except Exception:  # pragma: no cover
        pass
    log.info("email_provider_selected", provider="simulation")
    return _SimulationEmail()


email_service = _select_provider()
