"""Google Calendar integration.

Falls back to a no-op/local mode when credentials are not configured so the
system runs out of the box. Availability is still enforced via the database.
"""
import os
from datetime import datetime
from typing import Optional
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("gcal")

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarService:
    def __init__(self):
        self._service = None
        self.enabled = False
        self._try_init()

    def _try_init(self):
        if not os.path.exists(settings.google_credentials_file):
            log.info("gcal_disabled", reason="no_credentials_file")
            return
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            creds = None
            if os.path.exists(settings.google_token_file):
                creds = Credentials.from_authorized_user_file(settings.google_token_file, SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        settings.google_credentials_file, SCOPES)
                    creds = flow.run_local_server(port=0)
                with open(settings.google_token_file, "w") as f:
                    f.write(creds.to_json())
            self._service = build("calendar", "v3", credentials=creds)
            self.enabled = True
            log.info("gcal_enabled")
        except Exception as e:  # pragma: no cover
            log.warning("gcal_init_failed", error=str(e))

    def check_availability(self, calendar_id: str, start: datetime, end: datetime) -> bool:
        """Return True if the calendar has no overlapping busy block."""
        if not self.enabled or not calendar_id:
            return True  # DB remains the authority; calendar is a second gate
        try:
            body = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": calendar_id}],
            }
            res = self._service.freebusy().query(body=body).execute()
            busy = res["calendars"].get(calendar_id, {}).get("busy", [])
            return len(busy) == 0
        except Exception as e:  # pragma: no cover
            log.warning("gcal_check_failed", error=str(e))
            return True

    def create_event(self, calendar_id: str, summary: str, start: datetime,
                     end: datetime, description: str = "") -> Optional[str]:
        if not self.enabled or not calendar_id:
            return ""
        try:
            event = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            }
            created = self._service.events().insert(calendarId=calendar_id, body=event).execute()
            return created.get("id", "")
        except Exception as e:  # pragma: no cover
            log.warning("gcal_create_failed", error=str(e))
            return ""

    def cancel_event(self, calendar_id: str, event_id: str) -> bool:
        if not self.enabled or not calendar_id or not event_id:
            return True
        try:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return True
        except Exception as e:  # pragma: no cover
            log.warning("gcal_cancel_failed", error=str(e))
            return False


calendar_service = GoogleCalendarService()
