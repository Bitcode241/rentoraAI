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
    """Handles ONE mailbox. Configured by a dict from settings.mailboxes()."""

    def __init__(self, mailbox: dict | None = None):
        self.box = mailbox or {}
        self.address = self.box.get("address", "")
        self.enabled = bool(self.box.get("imap_host") and self.box.get("smtp_host")
                            and self.box.get("username"))

    # ---- reading ----
    def list_unread(self, max_results: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        out: List[Dict] = []
        try:
            conn = imaplib.IMAP4_SSL(self.box["imap_host"], self.box["imap_port"])
            conn.login(self.box["username"], self.box["password"])
            conn.select("INBOX")
            # Use UID search/fetch — UIDs are STABLE across connections, unlike
            # sequence numbers (which shift and caused mails to be missed/mismarked).
            status, data = conn.uid("search", None, "UNSEEN")
            if status != "OK":
                conn.logout()
                return []
            ids = data[0].split()
            for mid in ids[:max_results]:
                status, msgdata = conn.uid("fetch", mid, "(BODY.PEEK[])")
                if status != "OK":
                    continue
                raw = msgdata[0][1]
                msg = email.message_from_bytes(raw)
                from_name, from_addr = parseaddr(msg.get("From", ""))
                out.append({
                    "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                    "message_id": msg.get("Message-ID", "") or "",
                    "thread_id": msg.get("Message-ID", "") or "",
                    "from": msg.get("From", ""),
                    "from_email": from_addr,
                    "from_name": from_name or "",
                    "to": msg.get("To", ""),
                    "subject": _decode(msg.get("Subject", "")),
                    "body": _extract_body(msg),
                    "references": msg.get("References", "") or "",
                    "in_reply_to": msg.get("In-Reply-To", "") or "",
                    "mailbox": self.address,   # which of our addresses received it
                })
            conn.logout()
        except Exception as e:  # pragma: no cover
            log.warning("imap_list_failed", error=str(e), mailbox=self.address)
        return out

    def mark_read(self, message_id: str):
        if not self.enabled:
            return
        try:
            conn = imaplib.IMAP4_SSL(self.box["imap_host"], self.box["imap_port"])
            conn.login(self.box["username"], self.box["password"])
            conn.select("INBOX")
            conn.uid("store", message_id, "+FLAGS", "\\Seen")
            conn.logout()
        except Exception as e:  # pragma: no cover
            log.warning("imap_mark_failed", error=str(e), mailbox=self.address)

    # ---- sending ----
    def send(self, to: str, subject: str, body: str, thread_id: str = "",
             attachment: bytes = None, attachment_name: str = "potvrda.pdf") -> str:
        if not self.enabled:
            log.info("email_send_simulated", to=to, subject=subject, mailbox=self.address)
            return "simulated"
        try:
            if attachment:
                from email.mime.multipart import MIMEMultipart
                from email.mime.application import MIMEApplication
                mime = MIMEMultipart()
                mime.attach(MIMEText(body, "plain", "utf-8"))
                part = MIMEApplication(attachment, _subtype="pdf")
                part.add_header("Content-Disposition", "attachment",
                                filename=attachment_name)
                mime.attach(part)
            else:
                mime = MIMEText(body, "plain", "utf-8")
            mime["To"] = to
            mime["From"] = self.address or self.box["username"]
            mime["Subject"] = subject
            if thread_id:
                mime["In-Reply-To"] = thread_id
                mime["References"] = thread_id
            if self.box.get("use_ssl", True):
                server = smtplib.SMTP_SSL(self.box["smtp_host"], self.box["smtp_port"])
            else:
                server = smtplib.SMTP(self.box["smtp_host"], self.box["smtp_port"])
                server.starttls()
            server.login(self.box["username"], self.box["password"])
            server.send_message(mime)
            server.quit()
            log.info("email_sent", to=to, subject=subject, mailbox=self.address,
                     with_pdf=bool(attachment))
            return "sent"
        except Exception as e:  # pragma: no cover
            log.warning("smtp_send_failed", error=str(e), mailbox=self.address)
            return ""


class MultiMailboxManager:
    """Manages all configured mailboxes. Replies always go out from the address
    that received the message.

    Source of mailboxes (in priority order):
      1. Database (admin-panel managed) — the real, sellable way
      2. .env MAILBOXES_JSON or single EMAIL_* — fallback for bootstrapping
    """

    def __init__(self, mailboxes: list | None = None):
        self.services = {}
        self.type_map = {}   # asset_type -> mailbox address (e.g. "boat" -> seagull)
        boxes = mailboxes if mailboxes is not None else settings.mailboxes()
        for box in boxes:
            svc = ImapSmtpEmailService(box)
            if svc.enabled:
                self.services[svc.address] = svc
                htype = (box.get("handles_type") or "").strip().lower()
                if htype:
                    self.type_map[htype] = svc.address
        self.enabled = len(self.services) > 0
        if self.enabled:
            log.info("mailboxes_loaded", count=len(self.services),
                     addresses=list(self.services.keys()))

    def box_for_type(self, asset_type: str) -> str:
        """Pick the mailbox address assigned to this asset type (boat/jetski/
        transfer). Falls back to the first mailbox if none is tagged."""
        addr = self.type_map.get((asset_type or "").lower())
        if addr and addr in self.services:
            return addr
        return next(iter(self.services.keys()), "")

    @classmethod
    def from_db(cls, db):
        """Build the manager from active mailboxes stored in the database."""
        from app.models.mailbox import Mailbox
        rows = db.query(Mailbox).filter(Mailbox.active.is_(True)).all()
        boxes = [{
            "address": m.address, "username": m.username, "password": m.password,
            "imap_host": m.imap_host, "smtp_host": m.smtp_host,
            "imap_port": m.imap_port, "smtp_port": m.smtp_port, "use_ssl": m.use_ssl,
            "handles_type": getattr(m, "handles_type", "") or "",
        } for m in rows]
        if boxes:
            return cls(mailboxes=boxes)
        # No DB mailboxes yet -> fall back to .env so nothing breaks during setup
        return cls()

    def list_all_unread(self, max_per_box: int = 10) -> List[Dict]:
        out = []
        for svc in self.services.values():
            out.extend(svc.list_unread(max_results=max_per_box))
        return out

    def reply_from(self, mailbox_address: str, to: str, subject: str,
                   body: str, thread_id: str = "",
                   attachment: bytes = None, attachment_name: str = "potvrda.pdf") -> str:
        svc = self.services.get(mailbox_address)
        if not svc:
            svc = next(iter(self.services.values()), None)
        if not svc:
            log.info("email_send_simulated", to=to, subject=subject)
            return "simulated"
        return svc.send(to, subject, body, thread_id, attachment, attachment_name)

    def mark_read(self, mailbox_address: str, message_id: str):
        svc = self.services.get(mailbox_address)
        if svc:
            svc.mark_read(message_id)


# Backwards-compatible single-service handle (first .env mailbox, if any)
_boxes = settings.mailboxes()
imap_smtp_service = ImapSmtpEmailService(_boxes[0] if _boxes else None)
