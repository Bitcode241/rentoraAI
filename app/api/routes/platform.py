from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.platform import PlatformTerms, PlatformAcceptance

router = APIRouter(prefix="/api/platform", tags=["platform"])


def _current(db: Session, lang: str = "hr"):
    q = db.query(PlatformTerms).filter(PlatformTerms.active == True)  # noqa: E712
    return (q.filter(PlatformTerms.lang == lang).first()
            or q.filter(PlatformTerms.lang == "hr").first()
            or q.first())


@router.get("/terms")
def get_terms(lang: str = "hr", db: Session = Depends(get_db),
              _=Depends(get_current_user)):
    """Current platform terms + whether this user has accepted the latest version."""
    t = _current(db, lang)
    username = getattr(_, "username", "") or ""
    acc = (db.query(PlatformAcceptance)
           .filter(PlatformAcceptance.username == username)
           .order_by(PlatformAcceptance.accepted_at.desc())
           .first())
    needs = bool(t and (t.body or "").strip() and
                 (not acc or acc.terms_version != t.version))
    return {
        "exists": bool(t),
        "version": (t.version if t else 0),
        "title": (t.title if t else ""),
        "body": (t.body if t else ""),
        "lang": (t.lang if t else lang),
        "needs_acceptance": needs,
        "accepted": None if not acc else {
            "version": acc.terms_version,
            "at": acc.accepted_at,
            "by": acc.username,
            "business": acc.business_name,
        },
    }


@router.put("/terms")
def save_terms(payload: dict, db: Session = Depends(get_db),
               _=Depends(get_current_user)):
    """Write/update the platform terms. Any text change bumps the version, which
    means every customer is asked to accept the new wording."""
    from app.services import audit
    lang = (payload.get("lang") or "hr").strip()[:5]
    title = (payload.get("title") or "").strip()[:200]
    body = payload.get("body") or ""
    t = db.query(PlatformTerms).filter(PlatformTerms.lang == lang).first()
    if t:
        if (t.body or "") != body or (t.title or "") != title:
            t.version = (t.version or 1) + 1
        t.title, t.body, t.active = title, body, True
    else:
        t = PlatformTerms(lang=lang, title=title, body=body, version=1, active=True)
        db.add(t)
    db.commit()
    db.refresh(t)
    audit.record(db, "platform_terms_saved",
                 actor=getattr(_, "username", "admin"), entity="platform",
                 entity_id=t.id, detail=f"{lang} — verzija {t.version}")
    return {"ok": True, "version": t.version}


@router.post("/accept")
def accept_terms(payload: dict, request: Request, db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    """Record that this user accepted the current terms — with a copy of the text."""
    from app.services import audit, settings_service
    lang = (payload.get("lang") or "hr").strip()[:5]
    t = _current(db, lang)
    if not t or not (t.body or "").strip():
        raise HTTPException(400, "Uvjeti platforme nisu postavljeni.")
    username = getattr(_, "username", "") or ""
    acc = PlatformAcceptance(
        username=username,
        business_name=settings_service.business_name(db) or "",
        terms_version=t.version, lang=t.lang,
        title_snapshot=t.title or "", body_snapshot=t.body or "",
        accepted_ip=(request.client.host if request.client else "")[:60])
    db.add(acc)
    db.commit()
    audit.record(db, "platform_terms_accepted", actor=username,
                 entity="platform", entity_id=t.id,
                 detail=f"Prihvaćena verzija {t.version} ({t.lang})")
    return {"ok": True, "version": t.version}


@router.get("/acceptances")
def list_acceptances(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Who accepted what, and when — the platform owner's proof."""
    rows = (db.query(PlatformAcceptance)
            .order_by(PlatformAcceptance.accepted_at.desc()).limit(200).all())
    return {"acceptances": [{
        "id": a.id, "username": a.username, "business": a.business_name,
        "version": a.terms_version, "lang": a.lang, "at": a.accepted_at,
        "ip": a.accepted_ip} for a in rows]}
