"""Meeting points + WhatsApp for the confirmation email.

The owner lists their pickup/meeting locations (name + Google Maps link + notes)
in the admin. After a booking is paid, the confirmation email includes all of
them so the guest can pick whichever suits, navigate via the map pin, and open a
WhatsApp chat with one tap (a wa.me link — works with no Meta API approval).
"""
import json

from sqlalchemy.orm import Session

from app.services import settings_service

MEETING_POINTS_KEY = "meeting_points_json"
WHATSAPP_NUMBER_KEY = "whatsapp_number"


def get_meeting_points(db: Session) -> list:
    """Return the list of meeting points: [{name, maps_url, note}]."""
    raw = settings_service.get(db, MEETING_POINTS_KEY, "") or ""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def set_meeting_points(db: Session, points: list):
    clean = []
    for p in points or []:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        clean.append({
            "name": name,
            "maps_url": (p.get("maps_url") or "").strip(),
            "note": (p.get("note") or "").strip(),
            "primary": bool(p.get("primary")),
        })
    # ensure at most one primary; if none marked, the first becomes primary
    primaries = [p for p in clean if p["primary"]]
    if not primaries and clean:
        clean[0]["primary"] = True
    elif len(primaries) > 1:
        seen = False
        for p in clean:
            if p["primary"] and not seen:
                seen = True
            else:
                p["primary"] = False
    settings_service.set(db, MEETING_POINTS_KEY, json.dumps(clean, ensure_ascii=False))
    return clean


def get_whatsapp_number(db: Session) -> str:
    return settings_service.get(db, WHATSAPP_NUMBER_KEY, "") or ""


def set_whatsapp_number(db: Session, number: str):
    settings_service.set(db, WHATSAPP_NUMBER_KEY, (number or "").strip())


def wa_link(number: str, text: str = "") -> str:
    """Build a wa.me link that opens a WhatsApp chat to `number` (digits only)."""
    digits = "".join(ch for ch in (number or "") if ch.isdigit())
    if not digits:
        return ""
    url = f"https://wa.me/{digits}"
    if text:
        from urllib.parse import quote
        url += f"?text={quote(text)}"
    return url


# per-language labels for the meeting-point block
_LABELS = {
    "en": {"main": "WHERE TO MEET US", "directions": "Directions",
           "others_intro": "Prefer a different spot?",
           "others": "We can also meet at these locations — just let us know in advance "
                     "(most of our jet skis are based at our main point):",
           "questions": "Questions or a different location? Message us on WhatsApp:",
           "wa": "Open WhatsApp chat"},
    "hr": {"main": "GDJE NAS NAĐETE", "directions": "Upute",
           "others_intro": "Želite drugu lokaciju?",
           "others": "Možemo se naći i na ovim lokacijama — samo nam javite unaprijed "
                     "(većina skutera nam je na glavnoj lokaciji):",
           "questions": "Pitanja ili druga lokacija? Pišite nam na WhatsApp:",
           "wa": "Otvori WhatsApp chat"},
    "de": {"main": "TREFFPUNKT", "directions": "Wegbeschreibung",
           "others_intro": "Lieber ein anderer Ort?",
           "others": "Wir können uns auch hier treffen — bitte vorab Bescheid geben "
                     "(die meisten Jetskis sind an unserem Haupttreffpunkt):",
           "questions": "Fragen oder anderer Treffpunkt? Schreiben Sie uns auf WhatsApp:",
           "wa": "WhatsApp-Chat öffnen"},
}


def meeting_block_text(db: Session, lang: str = "en") -> str:
    """Confirmation-email block. The primary location is shown prominently with a
    map pin (guests can just show up there); the rest are 'available on request via
    WhatsApp' so the owner can prep the jet ski + staff for those spots."""
    points = get_meeting_points(db)
    wa = get_whatsapp_number(db)
    if not points and not wa:
        return ""
    lab = _LABELS.get(lang, _LABELS["en"])
    primary = next((p for p in points if p.get("primary")), points[0] if points else None)
    others = [p for p in points if p is not primary]
    lines = []
    if primary:
        lines.append(f"— {lab['main']} —")
        lines.append(f"{primary['name']}")
        if primary.get("note"):
            lines.append(primary["note"])
        if primary.get("maps_url"):
            lines.append(f"{lab['directions']}: {primary['maps_url']}")
        lines.append("")
    if others:
        lines.append(lab["others_intro"])
        lines.append(lab["others"])
        for p in others:
            lines.append(f"• {p['name']}")
        lines.append("")
    if wa:
        link = wa_link(wa)
        lines.append(f"{lab['questions']} {wa}")
        if link:
            lines.append(f"{lab['wa']}: {link}")
    return "\n".join(lines).strip()
