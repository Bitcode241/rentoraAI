"""Web push notifications — a booking pops up on the owner's phone.

Uses the Web Push standard, so it works from the browser/home-screen app without
an app store. Keys (VAPID) are generated once and kept in settings, so there is
nothing for the owner to configure.
"""
import base64
import json

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.push import PushSubscription
from app.services import settings_service

log = get_logger(__name__)

VAPID_PUBLIC_KEY = "vapid_public_key"
VAPID_PRIVATE_KEY = "vapid_private_key"
VAPID_SUBJECT = "vapid_subject"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def ensure_keys(db: Session) -> dict:
    """Return the VAPID key pair, generating it on first use."""
    pub = settings_service.get(db, VAPID_PUBLIC_KEY, "") or ""
    priv = settings_service.get(db, VAPID_PRIVATE_KEY, "") or ""
    if pub and priv:
        return {"public": pub, "private": priv}
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    v = Vapid()
    v.generate_keys()
    priv_int = v.private_key.private_numbers().private_value
    priv = _b64(priv_int.to_bytes(32, "big"))
    raw_pub = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    pub = _b64(raw_pub)
    settings_service.set(db, VAPID_PUBLIC_KEY, pub)
    settings_service.set(db, VAPID_PRIVATE_KEY, priv)
    db.commit()
    log.info("vapid_keys_generated")
    return {"public": pub, "private": priv}


def public_key(db: Session) -> str:
    return ensure_keys(db)["public"]


def save_subscription(db: Session, sub: dict, label: str = "") -> PushSubscription:
    """Store (or refresh) a device subscription."""
    endpoint = (sub or {}).get("endpoint", "")
    if not endpoint:
        raise ValueError("missing endpoint")
    keys = (sub or {}).get("keys", {}) or {}
    row = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint).first()
    if not row:
        row = PushSubscription(endpoint=endpoint)
        db.add(row)
    row.p256dh = keys.get("p256dh", "")
    row.auth = keys.get("auth", "")
    if label:
        row.label = label[:120]
    db.commit()
    log.info("push_subscription_saved", label=row.label or "device")
    return row


def remove_subscription(db: Session, endpoint: str):
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint).delete()
    db.commit()


def send_to_all(db: Session, title: str, body: str, url: str = "/admin") -> dict:
    """Push a message to every registered device. Dead devices are pruned."""
    subs = db.query(PushSubscription).all()
    if not subs:
        return {"sent": 0, "failed": 0, "devices": 0}
    keys = ensure_keys(db)
    subject = settings_service.get(db, VAPID_SUBJECT, "") or "mailto:info@rentoraai.com"
    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = failed = 0
    from pywebpush import webpush, WebPushException
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth},
                },
                data=payload,
                vapid_private_key=keys["private"],
                vapid_claims={"sub": subject},
            )
            sent += 1
        except WebPushException as e:  # pragma: no cover
            failed += 1
            code = getattr(getattr(e, "response", None), "status_code", 0)
            # 404/410 = the device unsubscribed or the endpoint expired
            if code in (404, 410):
                db.delete(s)
                db.commit()
                log.info("push_subscription_pruned", endpoint=s.endpoint[:40])
            else:
                log.warning("push_send_failed", error=str(e)[:200])
        except Exception as e:  # pragma: no cover
            failed += 1
            log.warning("push_send_error", error=str(e)[:200])
    return {"sent": sent, "failed": failed, "devices": len(subs)}
