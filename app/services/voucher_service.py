"""Partner voucher — an INTERNAL confirmation for the partner who operates a tour
on your behalf. It is NOT a tax/fiscal document and makes no fiscal claims. Its only
purpose: the partner can show that the guest paid YOU (your company), the partner did
not charge the guest, and they are operating the tour for you under your agreement.
"""
import io
from app.services.confirmation_service import _register_fonts


def build_voucher(*, business_name, booking_id, asset_name, when, guests,
                  guest_name="", guest_phone="", partner_name="",
                  settlement_summary="", balance_to_collect=0.0,
                  deposit_paid=0.0, total_price=0.0, transfer_note="",
                  pickup_location="", currency="EUR") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    font_reg, font_bold = _register_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    teal = colors.HexColor("#0f6a7d")
    teal_dark = colors.HexColor("#0a4d5c")
    gold = colors.HexColor("#c8a45c")
    ink = colors.HexColor("#0d2b32")
    grey = colors.HexColor("#5a6b6f")
    light = colors.HexColor("#eef3f3")

    # header
    c.setFillColor(teal_dark)
    c.rect(0, h - 46 * mm, w, 46 * mm, fill=1, stroke=0)
    c.setFillColor(teal)
    c.rect(0, h - 46 * mm, w, 42 * mm, fill=1, stroke=0)
    c.setFillColor(gold)
    c.rect(0, h - 47 * mm, w, 1.2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font_bold, 24)
    c.drawString(20 * mm, h - 22 * mm, business_name or "Rentora")
    c.setFont(font_reg, 12)
    c.drawString(20 * mm, h - 30 * mm, "VOUCHER ZA PARTNERA / PARTNER VOUCHER")
    c.setFont(font_reg, 8.5)
    c.setFillColor(colors.HexColor("#bfe0e6"))
    c.drawRightString(w - 20 * mm, h - 14 * mm, "Powered by Rentora AI Rental System")

    # voucher number badge
    badge_w, badge_h = 44 * mm, 12 * mm
    bx, by = w - 20 * mm - badge_w, h - 38 * mm
    c.setFillColor(gold)
    c.roundRect(bx, by, badge_w, badge_h, 2 * mm, fill=1, stroke=0)
    c.setFillColor(teal_dark)
    c.setFont(font_bold, 12)
    c.drawCentredString(bx + badge_w / 2, by + 4 * mm, f"VOUCHER #{booking_id}")

    # details card
    y = h - 64 * mm
    rows = [
        ("Partner", partner_name or "—"),
        ("Plovilo / Vessel", asset_name),
        ("Datum i vrijeme / Date", when),
        ("Broj osoba / Guests", str(guests)),
        ("Gost / Guest", guest_name or "—"),
        ("Telefon gosta / Phone", guest_phone or "—"),
    ]
    if pickup_location:
        rows.append(("Pickup", pickup_location))
    if transfer_note:
        rows.append(("Transfer", transfer_note))
    card_top = y + 8 * mm
    card_h = len(rows) * 11 * mm + 6 * mm
    c.setFillColor(light)
    c.roundRect(18 * mm, card_top - card_h, w - 36 * mm, card_h, 3 * mm, fill=1, stroke=0)
    for label, value in rows:
        c.setFont(font_reg, 10.5)
        c.setFillColor(grey)
        c.drawString(24 * mm, y, label.upper())
        c.setFillColor(ink)
        c.setFont(font_bold, 12)
        c.drawString(86 * mm, y, str(value))
        y -= 11 * mm

    # statement box — the whole point of the voucher
    y -= 10 * mm
    c.setFillColor(teal)
    box_h = 40 * mm
    c.roundRect(18 * mm, y - box_h, w - 36 * mm, box_h, 3 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font_bold, 11)
    c.drawString(24 * mm, y - 9 * mm, "POTVRDA / CONFIRMATION")
    c.setFont(font_reg, 9.5)
    if balance_to_collect and balance_to_collect > 0:
        statement = [
            f"Gost je platio depozit {deposit_paid:.2f} {currency} tvrtki {business_name or 'nama'}.",
            f"Partner NAPLAĆUJE gostu ostatak u gotovini na licu mjesta.",
            f"Guest paid a deposit to our company. Partner collects the remaining",
            f"balance below from the guest in cash on site.",
        ]
    else:
        statement = [
            f"Gost je platio cijelu rezervaciju tvrtki {business_name or 'nama'}.",
            "Partner pruža uslugu i NE naplaćuje gostu ništa na licu mjesta.",
            "Guest paid in full to our company. Partner does NOT collect anything",
            "from the guest on site. Settlement per our agreement.",
        ]
    yy = y - 16 * mm
    for line in statement:
        c.drawString(24 * mm, yy, line)
        yy -= 6 * mm

    # prominent "TO COLLECT FROM GUEST" box — so the partner knows exactly what to take
    if balance_to_collect and balance_to_collect > 0:
        cy = y - box_h - 6 * mm
        cbox_h = 20 * mm
        c.setFillColor(gold)
        c.roundRect(18 * mm, cy - cbox_h, w - 36 * mm, cbox_h, 3 * mm, fill=1, stroke=0)
        c.setFillColor(teal_dark)
        c.setFont(font_bold, 12)
        c.drawString(24 * mm, cy - 8 * mm, "NAPLATITI OD GOSTA / COLLECT FROM GUEST:")
        c.setFont(font_bold, 18)
        c.drawRightString(w - 24 * mm, cy - 13 * mm,
                          f"{balance_to_collect:.2f} {currency}")
        c.setFont(font_reg, 8)
        c.drawString(24 * mm, cy - 16 * mm, "u gotovini / in cash")
        y = cy - cbox_h

    # settlement line (internal)
    if settlement_summary:
        y = y - 12 * mm
        c.setFillColor(ink)
        c.setFont(font_bold, 10)
        c.drawString(20 * mm, y, "Obračun (interno): ")
        c.setFont(font_reg, 10)
        c.setFillColor(grey)
        c.drawString(20 * mm, y - 6 * mm, settlement_summary)

    # footer accents
    c.setFillColor(gold)
    c.rect(0, 0, w, 6 * mm, fill=1, stroke=0)
    c.setFillColor(teal)
    c.rect(0, 6 * mm, w, 1 * mm, fill=1, stroke=0)
    c.setFillColor(grey)
    c.setFont(font_reg, 8)
    c.drawString(20 * mm, 12 * mm,
                 "Interni dokument za partnera. Nije fiskalni račun. / "
                 "Internal partner document. Not a fiscal invoice.")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
