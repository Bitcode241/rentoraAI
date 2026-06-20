"""Partner voucher — an INTERNAL confirmation for the partner who operates a tour
on your behalf. It is NOT a tax/fiscal document and makes no fiscal claims. Its only
purpose: the partner can show that the guest paid YOU (your company), the partner did
not charge the guest, and they are operating the tour for you under your agreement.
"""
import io
from app.services.confirmation_service import _register_fonts


def build_voucher(*, business_name, booking_id, asset_name, when, guests,
                  tour_name="", guest_name="", guest_phone="", partner_name="",
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
        ("Tura / Tour", tour_name or "—"),
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


class PartnerVoucherError(Exception):
    """Raised when a partner voucher can't be issued because mandatory provider
    data (name, OIB) is missing. Blocks voucher generation."""


def build_partner_voucher(*, business_name, business_oib="", booking_id,
                          asset_name, when, guests, tour_name="",
                          guest_name="", guest_phone="",
                          provider_name="", provider_oib="",
                          my_commission=0.0, pay_on_site=0.0, total_price=0.0,
                          pickup_location="", transfer_note="",
                          qr_png=None,
                          currency="EUR") -> bytes:
    """Legally-structured PARTNER voucher (NOT a fiscal receipt).

    The agency acts as an intermediary (u ime i za račun izvođača). The provider
    (izvođač) is responsible for performing the tour. Payment is split:
      - paid via agency (reservation): my_commission
      - to pay directly to provider on the boat: pay_on_site
      - total tour price: total_price

    MANDATORY: provider_name and provider_oib. If missing -> PartnerVoucherError,
    no voucher is issued.
    """
    if not (provider_name or "").strip() or not (provider_oib or "").strip():
        raise PartnerVoucherError("provider_name_or_oib_missing")

    import io
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

    def wrap(text, font, size, max_w):
        from reportlab.pdfbase.pdfmetrics import stringWidth
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

    # ---- header ----
    c.setFillColor(teal_dark); c.rect(0, h - 46 * mm, w, 46 * mm, fill=1, stroke=0)
    c.setFillColor(teal); c.rect(0, h - 46 * mm, w, 42 * mm, fill=1, stroke=0)
    c.setFillColor(gold); c.rect(0, h - 47 * mm, w, 1.2 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font_bold, 22)
    c.drawString(20 * mm, h - 22 * mm, business_name or "Rentora")
    c.setFont(font_reg, 12)
    c.drawString(20 * mm, h - 31 * mm, "VAUCHER ZA IZLET / TOUR VOUCHER")
    c.setFont(font_reg, 9)
    c.setFillColor(colors.HexColor("#bfe0e6"))
    c.drawString(20 * mm, h - 39 * mm,
                 "Agencija nastupa kao POSREDNIK — u ime i za račun izvođača.")

    y = h - 58 * mm

    # ---- intermediary / provider block ----
    rows = [
        ("Rezervacija br.", f"#{booking_id}"),
        ("Posrednik (agencija)", business_name + (f", OIB: {business_oib}" if business_oib else "")),
        ("Izvođač izleta", provider_name),
        ("OIB izvođača", provider_oib),
        ("Izvođač je odgovoran za", "izvršenje izleta"),
        ("Izlet / plovilo", (tour_name + " — " if tour_name else "") + (asset_name or "")),
        ("Datum i vrijeme", when),
        ("Broj osoba", str(guests)),
    ]
    if pickup_location:
        rows.append(("Mjesto polaska", pickup_location))
    if guest_name:
        rows.append(("Gost", guest_name))
    if guest_phone:
        rows.append(("Telefon gosta", guest_phone))
    if transfer_note:
        rows.append(("Napomena", transfer_note))

    val_max_w = (w - 24 * mm) - (78 * mm)
    wrapped = [(lbl, wrap(val, font_bold, 11, val_max_w)) for lbl, val in rows]
    line_h = 5.0 * mm
    row_h = 9.5 * mm
    total_h = sum(max(row_h, line_h * len(ls) + 4 * mm) for _, ls in wrapped)

    card_top = y + 6 * mm
    c.setFillColor(light)
    c.roundRect(18 * mm, card_top - (total_h + 6 * mm), w - 36 * mm,
                total_h + 6 * mm, 3 * mm, fill=1, stroke=0)
    for lbl, lines in wrapped:
        c.setFont(font_reg, 9.5); c.setFillColor(grey)
        c.drawString(23 * mm, y, lbl.upper())
        c.setFont(font_bold, 11); c.setFillColor(ink)
        ly = y
        for ln in lines:
            c.drawString(78 * mm, ly, ln); ly -= line_h
        y -= max(row_h, line_h * len(lines) + 4 * mm)

    # ---- split payment box ----
    y -= 8 * mm
    box_h = 40 * mm
    c.setFillColor(teal)
    c.roundRect(18 * mm, y - box_h, w - 36 * mm, box_h, 3 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font_reg, 11)
    c.drawString(24 * mm, y - 9 * mm, "Plaćeno putem agencije (rezervacija):")
    c.setFont(font_bold, 13)
    c.drawRightString(w - 24 * mm, y - 9 * mm, f"{my_commission:.2f} {currency}")

    c.setFillColor(gold)
    c.setFont(font_bold, 13)
    c.drawString(24 * mm, y - 20 * mm, "ZA PLATITI IZRAVNO IZVOĐAČU NA BRODU:")
    c.drawRightString(w - 24 * mm, y - 20 * mm, f"{pay_on_site:.2f} {currency}")

    c.setStrokeColor(colors.HexColor("#2a8497"))
    c.line(24 * mm, y - 26 * mm, w - 24 * mm, y - 26 * mm)
    c.setFillColor(colors.white)
    c.setFont(font_reg, 11)
    c.drawString(24 * mm, y - 34 * mm, "Ukupna cijena izleta:")
    c.setFont(font_bold, 13)
    c.drawRightString(w - 24 * mm, y - 34 * mm, f"{total_price:.2f} {currency}")

    y -= box_h + 12 * mm

    # ---- mandatory note + QR ----
    c.setFillColor(ink)
    c.setFont(font_bold, 11)
    c.drawString(20 * mm, y, "Ovaj voucher predočite izvođaču pri dolasku.")

    if qr_png:
        try:
            from reportlab.lib.utils import ImageReader
            qr_size = 30 * mm
            qr_x = w - 24 * mm - qr_size
            qr_y = y - qr_size + 4 * mm
            c.drawImage(ImageReader(io.BytesIO(qr_png)), qr_x, qr_y,
                        qr_size, qr_size, mask="auto")
            c.setFont(font_reg, 7.5)
            c.setFillColor(grey)
            c.drawCentredString(qr_x + qr_size / 2, qr_y - 4 * mm,
                                "Skenirajte za detalje")
        except Exception:
            pass
    y -= 12 * mm

    # ---- non-fiscal footer ----
    c.setFillColor(grey)
    c.setFont(font_reg, 8.5)
    for ln in wrap("Ovo nije fiskalni račun. Fiskalni račun za proviziju izdaje "
                   "agencija, a za svoj dio izvođač izleta. Agencija je posredovala "
                   "u ime i za račun izvođača.", font_reg, 8.5, w - 40 * mm):
        c.drawString(20 * mm, y, ln); y -= 4.5 * mm
    c.setFont(font_reg, 8)
    c.drawString(20 * mm, 12 * mm, "Powered by RentoraAI Rental System")

    c.showPage(); c.save()
    return buf.getvalue()
