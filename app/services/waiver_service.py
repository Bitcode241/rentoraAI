"""Waivers — the terms a guest signs before going out.

Design decisions worth knowing:

* The text belongs to the owner, per asset type and per language. Nothing is
  hard-coded, because a jet ski waiver, a boat waiver and a transfer waiver are
  different documents, and every business words them differently.
* A signature stores its own copy of the text. Editing the template afterwards
  bumps the version and never touches what was already signed.
"""
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.waiver import WaiverTemplate, WaiverSignature

log = get_logger(__name__)

LANGS = ("en", "hr", "de")


def get_template(db: Session, asset_type: str, lang: str = "en"):
    """Best match: exact type+language, then type+English, then any active one."""
    q = db.query(WaiverTemplate).filter(WaiverTemplate.active == True)  # noqa: E712
    t = q.filter(WaiverTemplate.asset_type == asset_type,
                 WaiverTemplate.lang == lang).first()
    if t:
        return t
    t = q.filter(WaiverTemplate.asset_type == asset_type,
                 WaiverTemplate.lang == "en").first()
    if t:
        return t
    return q.filter(WaiverTemplate.asset_type == asset_type).first()


def save_template(db: Session, *, asset_type: str, lang: str, title: str,
                  body: str, require_document: bool = True,
                  template_id: int = None) -> WaiverTemplate:
    """Create or update. Any change to the text bumps the version so signatures
    can be traced back to exactly which wording was in force."""
    t = db.get(WaiverTemplate, template_id) if template_id else None
    if not t:
        t = db.query(WaiverTemplate).filter(
            WaiverTemplate.asset_type == asset_type,
            WaiverTemplate.lang == lang).first()
    if t:
        if (t.body or "") != (body or "") or (t.title or "") != (title or ""):
            t.version = (t.version or 1) + 1
        t.title, t.body = title, body
        t.require_document = require_document
        t.active = True
    else:
        t = WaiverTemplate(asset_type=asset_type, lang=lang, title=title,
                           body=body, require_document=require_document,
                           version=1, active=True)
        db.add(t)
    db.commit()
    db.refresh(t)
    log.info("waiver_template_saved", asset_type=asset_type, lang=lang,
             version=t.version)
    return t


def signature_for(db: Session, booking_id: int):
    return (db.query(WaiverSignature)
            .filter(WaiverSignature.booking_id == booking_id)
            .order_by(WaiverSignature.signed_at.desc())
            .first())


def sign_token(db: Session, booking_id: int) -> str:
    """Stable per-booking link the guest opens to sign (QR-friendly)."""
    existing = (db.query(WaiverSignature)
                .filter(WaiverSignature.booking_id == booking_id).first())
    if existing and existing.token:
        return existing.token
    return secrets.token_urlsafe(16)


def record_signature(db: Session, *, booking_id: int, template,
                     signer_name: str, signer_document: str = "",
                     signer_birth: str = "", signature_png: str = "",
                     lang: str = "en", ip: str = "",
                     token: str = "") -> WaiverSignature:
    if not signer_name.strip():
        raise ValueError("Ime potpisnika je obavezno.")
    if not signature_png:
        raise ValueError("Potpis je obavezan.")
    if template and template.require_document and not signer_document.strip():
        raise ValueError("Broj dokumenta je obavezan.")
    sig = WaiverSignature(
        booking_id=booking_id,
        template_id=(template.id if template else None),
        template_version=(template.version if template else 1),
        asset_type=(template.asset_type if template else ""),
        lang=lang,
        # snapshot: what the guest actually read, frozen at this moment
        title_snapshot=(template.title if template else ""),
        body_snapshot=(template.body if template else ""),
        signer_name=signer_name.strip()[:160],
        signer_document=signer_document.strip()[:80],
        signer_birth=(signer_birth or "").strip()[:20],
        signature_png=signature_png,
        signed_ip=(ip or "")[:60],
        token=token or secrets.token_urlsafe(16),
        signed_at=datetime.now(timezone.utc),
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)
    log.info("waiver_signed", booking_id=booking_id, signer=sig.signer_name,
             version=sig.template_version)
    return sig
