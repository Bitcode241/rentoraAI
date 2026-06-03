"""Gmail integration. Falls back to log-only mode without credentials."""
import os
import base64
from email.mime.text import MIMEText
from typing import List, Dict
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("gmail")
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


class GmailService:
    def __init__(self):
        self._service = None
        self.enabled = False
        self._try_init()

    def _try_init(self):
        if not os.path.exists(settings.google_credentials_file):
            log.info("gmail_disabled", reason="no_credentials_file")
            return
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            token = settings.google_token_file
            if os.path.exists(token):
                creds = Credentials.from_authorized_user_file(token, SCOPES)
                self._service = build("gmail", "v1", credentials=creds)
                self.enabled = True
                log.info("gmail_enabled")
        except Exception as e:  # pragma: no cover
            log.warning("gmail_init_failed", error=str(e))

    def list_unread(self, max_results: int = 10) -> List[Dict]:
        if not self.enabled:
            return []
        try:
            res = self._service.users().messages().list(
                userId="me", q="is:unread", maxResults=max_results).execute()
            out = []
            for m in res.get("messages", []):
                full = self._service.users().messages().get(
                    userId="me", id=m["id"], format="full").execute()
                out.append(self._parse(full))
            return out
        except Exception as e:  # pragma: no cover
            log.warning("gmail_list_failed", error=str(e))
            return []

    def _parse(self, msg: Dict) -> Dict:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        body = ""
        payload = msg["payload"]
        parts = payload.get("parts", [payload])
        for p in parts:
            data = p.get("body", {}).get("data")
            if data:
                body += base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "body": body,
        }

    def send(self, to: str, subject: str, body: str, thread_id: str = "") -> str:
        if not self.enabled:
            log.info("gmail_send_simulated", to=to, subject=subject)
            return "simulated"
        try:
            mime = MIMEText(body)
            mime["to"] = to
            mime["from"] = settings.gmail_user or "me"
            mime["subject"] = subject
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            payload = {"raw": raw}
            if thread_id:
                payload["threadId"] = thread_id
            sent = self._service.users().messages().send(userId="me", body=payload).execute()
            return sent.get("id", "")
        except Exception as e:  # pragma: no cover
            log.warning("gmail_send_failed", error=str(e))
            return ""

    def mark_read(self, message_id: str):
        if not self.enabled:
            return
        try:
            self._service.users().messages().modify(
                userId="me", id=message_id,
                body={"removeLabelIds": ["UNREAD"]}).execute()
        except Exception as e:  # pragma: no cover
            log.warning("gmail_mark_failed", error=str(e))


gmail_service = GmailService()
