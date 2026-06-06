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
        "package": "Paket",
        "deposit_paid": "Plaćeni depozit",
        "full_price": "Ukupna cijena",
        "balance": "Za platiti na licu mjesta",
        "transfer_inc": "Transfer uključen",
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
        "package": "Package",
        "deposit_paid": "Deposit paid",
        "full_price": "Total price",
        "balance": "Balance due on site",
        "transfer_inc": "Transfer included",
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
        "package": "Paket",
        "deposit_paid": "Angezahlt",
        "full_price": "Gesamtpreis",
        "balance": "Restzahlung vor Ort",
        "transfer_inc": "Transfer inklusive",
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


def build_pdf(*, lang, business_name, booking_id, asset_name, when, guests,
              package, deposit_paid, full_price, balance, transfer_included,
              location, phone="", currency="EUR") -> bytes:
    """Return a PDF receipt as bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    tr = _t(lang)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    teal = colors.HexColor("#0f6a7d")
    ink = colors.HexColor("#0d2b32")

    # header band
    c.setFillColor(teal)
    c.rect(0, h - 40 * mm, w, 40 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(20 * mm, h - 22 * mm, business_name or "Rentora")
    c.setFont("Helvetica", 13)
    c.drawString(20 * mm, h - 31 * mm, tr["title"])

    # body rows
    y = h - 58 * mm
    rows = [
        (tr["booking_no"], f"#{booking_id}"),
        (tr["vessel"], asset_name),
        (tr["date"], when),
        (tr["guests"], str(guests)),
    ]
    if package:
        rows.append((tr["package"], package))
    rows += [
        (tr["transfer_inc"], tr["yes"] if transfer_included else tr["no"]),
    ]
    if location:
        rows.append((tr["location"], location))
    if phone:
        rows.append((tr["phone"], phone))

    c.setFillColor(ink)
    for label, value in rows:
        c.setFont("Helvetica", 11)
        c.setFillColor(colors.HexColor("#5a6b6f"))
        c.drawString(20 * mm, y, label)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(80 * mm, y, str(value))
        y -= 11 * mm

    # money box
    y -= 6 * mm
    c.setStrokeColor(colors.HexColor("#dfe6e6"))
    c.line(20 * mm, y, w - 20 * mm, y)
    y -= 12 * mm
    money = [
        (tr["full_price"], f"{full_price:.2f} {currency}"),
        (tr["deposit_paid"], f"-{deposit_paid:.2f} {currency}"),
        (tr["balance"], f"{balance:.2f} {currency}"),
    ]
    for i, (label, value) in enumerate(money):
        bold = (i == len(money) - 1)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 13 if bold else 11)
        c.setFillColor(ink if bold else colors.HexColor("#5a6b6f"))
        c.drawString(20 * mm, y, label)
        c.drawRightString(w - 20 * mm, y, value)
        y -= 10 * mm

    # footer
    c.setFont("Helvetica", 11)
    c.setFillColor(ink)
    c.drawString(20 * mm, 30 * mm, tr["thanks"])
    c.setFillColor(colors.HexColor("#5a6b6f"))
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, 22 * mm, tr["questions"])

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def email_text(lang: str, business_name: str) -> tuple:
    tr = _t(lang)
    return tr["subject"], f"{tr['intro']}\n\n{tr['thanks']}\n\n{business_name or 'Rentora'}"
