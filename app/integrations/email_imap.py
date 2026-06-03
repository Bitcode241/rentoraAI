"""IMAP/SMTP email integration for mailcow, custom domains, or Gmail.

Same interface as the Gmail service (list_unread / send / mark_read) so the
rest of the system is provider-agnostic. Falls back to simulation mode (logs
instead of sending/reading) when EMAIL_IMAP_HOST / EMAIL_SMTP_HOST are blank.
"""
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.header import decode_header
from email.utils import parseaddr, formataddr
from typing import List, Dict
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("email-imap")


def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out += text.decode(enc or "utf-8", "ignore")
            except (LookupError, TypeError):
                out += text.decode("utf-8", "ignore")
        else:
            out += text
    return out


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in disp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, "ignore")
        # fallback to html if no plain part
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, "ignore")
        return ""
    payload = msg.get_payload(decode=True)
    if payload:
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, "ignore")
    return ""


class ImapSmtpEmailService:
    def __init__(self):
        self.enabled = bool(settings.email_imap_host and settings.email_smtp_host
                            and settings.email_username)
        if not self.enabled:
            log.info("email_disabled", reason="imap_smtp_not_configured")

    # ---- reading ----
    def list_unread(self, max_results: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        out: List[Dict] = []
        try:
            conn = imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port)
            conn.login(settings.email_username, settings.email_password)
            conn.select("INBOX")
            status, data = conn.search(None, "UNSEEN")
            if status != "OK":
                conn.logout()
                return []
            ids = data[0].split()
            for mid in ids[:max_results]:
                # PEEK so we don't mark read until we choose to
                status, msgdata = conn.fetch(mid, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                raw = msgdata[0][1]
                msg = email.message_from_bytes(raw)
                from_name, from_addr = parseaddr(msg.get("From", ""))
                out.append({
                    "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "thread_id": msg.get("Message-ID", "") or "",
                    "from": msg.get("From", ""),
                    "from_email": from_addr,
                    "to": msg.get("To", ""),
                    "subject": _decode(msg.get("Subject", "")),
                    "body": _extract_body(msg),
                    "references": msg.get("References", ""),
                    "in_reply_to": msg.get("Message-ID", ""),
                })
            conn.logout()
        except Exception as e:  # pragma: no cover
            log.warning("imap_list_failed", error=str(e))
        return out

    def mark_read(self, message_id: str):
        if not self.enabled:
            return
        try:
            conn = imaplib.IMAP4_SSL(settings.email_imap_host, settings.email_imap_port)
            conn.login(settings.email_username, settings.email_password)
            conn.select("INBOX")
            conn.store(message_id, "+FLAGS", "\\Seen")
            conn.logout()
        except Exception as e:  # pragma: no cover
            log.warning("imap_mark_failed", error=str(e))

    # ---- sending ----
    def send(self, to: str, subject: str, body: str, thread_id: str = "") -> str:
        if not self.enabled:
            log.info("email_send_simulated", to=to, subject=subject)
            return "simulated"
        try:
            mime = MIMEText(body, "plain", "utf-8")
            mime["To"] = to
            mime["From"] = settings.email_from or settings.email_username
            mime["Subject"] = subject
            if thread_id:
                mime["In-Reply-To"] = thread_id
                mime["References"] = thread_id
            if settings.email_use_ssl:
                server = smtplib.SMTP_SSL(settings.email_smtp_host, settings.email_smtp_port)
            else:
                server = smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port)
                server.starttls()
            server.login(settings.email_username, settings.email_password)
            server.send_message(mime)
            server.quit()
            log.info("email_sent", to=to, subject=subject)
            return "sent"
        except Exception as e:  # pragma: no cover
            log.warning("smtp_send_failed", error=str(e))
            return ""


imap_smtp_service = ImapSmtpEmailService()
