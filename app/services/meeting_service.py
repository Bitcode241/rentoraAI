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
        })
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
    "en": {"where": "WHERE TO MEET US", "pick": "Choose whichever location works best for you:",
           "directions": "Directions", "questions": "Questions? Message us on WhatsApp:",
           "wa": "Open WhatsApp chat"},
    "hr": {"where": "GDJE NAS NAĐETE", "pick": "Odaberite lokaciju koja Vam najviše odgovara:",
           "directions": "Upute", "questions": "Pitanja? Pišite nam na WhatsApp:",
           "wa": "Otvori WhatsApp chat"},
    "de": {"where": "TREFFPUNKTE", "pick": "Wählen Sie den passenden Treffpunkt:",
           "directions": "Wegbeschreibung", "questions": "Fragen? Schreiben Sie uns auf WhatsApp:",
           "wa": "WhatsApp-Chat öffnen"},
}


def meeting_block_text(db: Session, lang: str = "en") -> str:
    """Plain-text meeting-point block appended to the confirmation email body.
    Returns '' if the owner hasn't configured any points."""
    points = get_meeting_points(db)
    wa = get_whatsapp_number(db)
    if not points and not wa:
        return ""
    lab = _LABELS.get(lang, _LABELS["en"])
    lines = []
    if points:
        lines.append(f"— {lab['where']} —")
        lines.append(lab["pick"])
        lines.append("")
        for p in points:
            lines.append(f"• {p['name']}")
            if p.get("note"):
                lines.append(f"  {p['note']}")
            if p.get("maps_url"):
                lines.append(f"  {lab['directions']}: {p['maps_url']}")
            lines.append("")
    if wa:
        link = wa_link(wa)
        lines.append(f"{lab['questions']} {wa}")
        if link:
            lines.append(f"{lab['wa']}: {link}")
    return "\n".join(lines).strip()
