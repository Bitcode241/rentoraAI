"""Booking confirmation: a professional PDF receipt + a multilingual email.

Works for ANY booking type (boat, jetski, transfer). Shows: asset, date/time,
guests, deposit paid, full price, balance due on site, whether a transfer is
included, and arrival info. Localized to the guest's language (hr/en/de).
"""
import io
from datetime import datetime
from app.core.logging import get_logger

log = get_logger(__name__)

# ---- translations ----
T = {
    "hr": {
        "title": "Potvrda rezervacije",
        "booking_no": "Broj rezervacije",
        "vessel": "Plovilo / Usluga",
        "date": "Datum i vrijeme",
        "guests": "Broj osoba",
        "phone": "Kontakt telefon",
        "guest_name": "Gost",
        "guest_email": "Email gosta",
        "package": "Paket",
        "deposit_paid": "Plaćeni depozit",
        "full_price": "Ukupna cijena",
        "balance": "Za platiti na licu mjesta",
        "transfer_inc": "Transfer uključen",
        "extras": "Dodatno",
        "paid_badge": "PLAĆENO",
        "yes": "Da", "no": "Ne",
        "location": "Lokacija polaska",
        "thanks": "Hvala na rezervaciji! Veselimo se Vašem dolasku.",
        "questions": "Za sva pitanja samo odgovorite na ovaj email.",
        "subject": "Potvrda rezervacije",
        "intro": "Vaša rezervacija je potvrđena. U privitku je potvrda u PDF formatu.",
    },
    "en": {
        "title": "Booking Confirmation",
        "booking_no": "Booking number",
        "vessel": "Vessel / Service",
        "date": "Date & time",
        "guests": "Guests",
        "phone": "Contact phone",
        "guest_name": "Guest",
        "guest_email": "Guest email",
        "package": "Package",
        "deposit_paid": "Deposit paid",
        "full_price": "Total price",
        "balance": "Balance due on site",
        "transfer_inc": "Transfer included",
        "extras": "Extras",
        "paid_badge": "PAID",
        "yes": "Yes", "no": "No",
        "location": "Departure location",
        "thanks": "Thank you for your booking! We look forward to seeing you.",
        "questions": "For any questions, just reply to this email.",
        "subject": "Booking Confirmation",
        "intro": "Your booking is confirmed. The confirmation is attached as a PDF.",
    },
    "de": {
        "title": "Buchungsbestätigung",
        "booking_no": "Buchungsnummer",
        "vessel": "Boot / Leistung",
        "date": "Datum & Uhrzeit",
        "guests": "Personen",
        "phone": "Telefon",
        "guest_name": "Gast",
        "guest_email": "Gast E-Mail",
        "package": "Paket",
        "deposit_paid": "Angezahlt",
        "full_price": "Gesamtpreis",
        "balance": "Restzahlung vor Ort",
        "transfer_inc": "Transfer inklusive",
        "extras": "Zusätzlich",
        "paid_badge": "BEZAHLT",
        "yes": "Ja", "no": "Nein",
        "location": "Abfahrtsort",
        "thanks": "Vielen Dank für Ihre Buchung! Wir freuen uns auf Sie.",
        "questions": "Bei Fragen antworten Sie einfach auf diese E-Mail.",
        "subject": "Buchungsbestätigung",
        "intro": "Ihre Buchung ist bestätigt. Die Bestätigung finden Sie im PDF-Anhang.",
    },
}


def _t(lang: str) -> dict:
    return T.get((lang or "en").lower()[:2], T["en"])


_FONTS_READY = None

def _register_fonts():
    """Register DejaVu (Unicode) fonts if available; return (regular, bold) names.
    Falls back to Helvetica if the TTFs aren't present (no crash)."""
    global _FONTS_READY
    if _FONTS_READY is not None:
        return _FONTS_READY
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
        base = "/usr/share/fonts/truetype/dejavu"
        reg = os.path.join(base, "DejaVuSans.ttf")
        bold = os.path.join(base, "DejaVuSans-Bold.ttf")
        if os.path.exists(reg) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
            _FONTS_READY = ("DejaVu", "DejaVu-Bold")
            return _FONTS_READY
    except Exception:
        pass
    _FONTS_READY = ("Helvetica", "Helvetica-Bold")
    return _FONTS_READY


def build_pdf(*, lang, business_name, booking_id, asset_name, when, guests,
              package, deposit_paid, full_price, balance, transfer_included,
              location, phone="", guest_name="", guest_email="",
              transfer_note="", currency="EUR") -> bytes:
    """Return a polished, professional PDF confirmation as bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    # Use a Unicode font so Croatian/German characters (č, ć, ž, š, đ, ü) render.
    font_reg, font_bold = _register_fonts()
    font_obl = font_reg  # oblique optional; fall back to regular

    tr = _t(lang)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    teal = colors.HexColor("#0f6a7d")
    teal_dark = colors.HexColor("#0a4d5c")
    gold = colors.HexColor("#c8a45c")
    ink = colors.HexColor("#0d2b32")
    grey = colors.HexColor("#5a6b6f")
    light = colors.HexColor("#eef3f3")
    line_col = colors.HexColor("#dfe6e6")

    # ---- header band with gradient-like layering ----
    c.setFillColor(teal_dark)
    c.rect(0, h - 46 * mm, w, 46 * mm, fill=1, stroke=0)
    c.setFillColor(teal)
    c.rect(0, h - 46 * mm, w, 42 * mm, fill=1, stroke=0)
    # thin gold accent line under header
    c.setFillColor(gold)
    c.rect(0, h - 47 * mm, w, 1.2 * mm, fill=1, stroke=0)

    c.setFillColor(colors.white)
    c.setFont(font_bold, 24)
    c.drawString(20 * mm, h - 22 * mm, business_name or "Rentora")
    c.setFont(font_reg, 12)
    c.drawString(20 * mm, h - 30 * mm, tr["title"])
    # small system tag, top-right
    c.setFont(font_obl, 8.5)
    c.setFillColor(colors.HexColor("#bfe0e6"))
    c.drawRightString(w - 20 * mm, h - 14 * mm, "Powered by Rentora AI Rental System")

    # ---- PAID badge ----
    badge_w, badge_h = 38 * mm, 12 * mm
    bx, by = w - 20 * mm - badge_w, h - 38 * mm
    c.setFillColor(gold)
    c.roundRect(bx, by, badge_w, badge_h, 2 * mm, fill=1, stroke=0)
    c.setFillColor(teal_dark)
    c.setFont(font_bold, 12)
    c.drawCentredString(bx + badge_w / 2, by + 4 * mm, tr["paid_badge"])

    # ---- details card ----
    y = h - 64 * mm
    rows = [
        (tr["booking_no"], f"#{booking_id}"),
        (tr["vessel"], asset_name),
        (tr["date"], when),
        (tr["guests"], str(guests)),
    ]
    if package:
        rows.append((tr["package"], package))
    # Extras / transfer row. The note can carry add-ons, an extra-person fee,
    # and/or a transfer. Label it "Transfer" only when it's actually a transfer;
    # otherwise use a neutral "Dodatno / Extras" label so we never mislabel fees.
    if transfer_note:
        note_l = transfer_note.lower()
        label = tr["transfer_inc"] if "transfer" in note_l else tr["extras"]
        rows.append((label, transfer_note))
    elif transfer_included:
        rows.append((tr["transfer_inc"], tr["yes"]))
    if location:
        rows.append((tr["location"], location))
    # Guest contact details — so the skipper can reach them on the day.
    if guest_name:
        rows.append((tr["guest_name"], guest_name))
    if phone:
        rows.append((tr["phone"], phone))
    if guest_email:
        rows.append((tr["guest_email"], guest_email))

    from reportlab.pdfbase.pdfmetrics import stringWidth

    def _wrap(text, font, size, max_w):
        """Split text into lines that fit max_w (points)."""
        words = str(text).split()
        if not words:
            return [""]
        lines, cur = [], words[0]
        for wd in words[1:]:
            if stringWidth(cur + " " + wd, font, size) <= max_w:
                cur += " " + wd
            else:
                lines.append(cur); cur = wd
        lines.append(cur)
        return lines

    # value column runs from x=82mm to the right padding (~w-24mm)
    val_max_w = (w - 24 * mm) - (82 * mm)
    # pre-compute wrapped lines + each row's height
    wrapped = []
    for label, value in rows:
        lines = _wrap(value, font_bold, 12, val_max_w)
        wrapped.append((label, lines))
    row_h = 11 * mm
    line_h = 5.2 * mm
    total_h = sum(max(row_h, line_h * len(ls) + 5 * mm) for _, ls in wrapped)

    card_top = y + 8 * mm
    card_h = total_h + 6 * mm
    c.setFillColor(light)
    c.roundRect(18 * mm, card_top - card_h, w - 36 * mm, card_h, 3 * mm, fill=1, stroke=0)

    for label, lines in wrapped:
        c.setFont(font_reg, 10.5)
        c.setFillColor(grey)
        c.drawString(24 * mm, y, label.upper())
        c.setFillColor(ink)
        c.setFont(font_bold, 12)
        ly = y
        for ln in lines:
            c.drawString(82 * mm, ly, ln)
            ly -= line_h
        y -= max(row_h, line_h * len(lines) + 5 * mm)

    # ---- money box ----
    y -= 10 * mm
    c.setFillColor(teal)
    c.roundRect(18 * mm, y - 34 * mm, w - 36 * mm, 38 * mm, 3 * mm, fill=1, stroke=0)
    my = y
    money = [
        (tr["full_price"], f"{full_price:.2f} {currency}", False),
        (tr["deposit_paid"], f"- {deposit_paid:.2f} {currency}", False),
        (tr["balance"], f"{balance:.2f} {currency}", True),
    ]
    my -= 4 * mm
    for label, value, bold in money:
        c.setFillColor(colors.white)
        c.setFont(font_bold if bold else font_reg, 14 if bold else 11)
        c.drawString(24 * mm, my, label)
        c.drawRightString(w - 24 * mm, my, value)
        if not bold:
            my -= 9 * mm
        else:
            my -= 9 * mm

    # ---- footer ----
    c.setFillColor(ink)
    c.setFont(font_bold, 11)
    c.drawString(20 * mm, 34 * mm, tr["thanks"])
    c.setFillColor(grey)
    c.setFont(font_reg, 9)
    c.drawString(20 * mm, 27 * mm, tr["questions"])
    # bottom accent
    c.setFillColor(gold)
    c.rect(0, 0, w, 6 * mm, fill=1, stroke=0)
    c.setFillColor(teal)
    c.rect(0, 6 * mm, w, 1 * mm, fill=1, stroke=0)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def email_text(lang: str, business_name: str) -> tuple:
    tr = _t(lang)
    return tr["subject"], f"{tr['intro']}\n\n{tr['thanks']}\n\n{business_name or 'Rentora'}"
