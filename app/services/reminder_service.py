"""Day-before reminders.

Once a day, finds confirmed bookings starting in the next ~24-48h window and:
  - emails the OWNER a summary of tomorrow's tours (so nothing is forgotten)
  - emails each GUEST a friendly reminder of their booking

Uses a 'reminder_sent' flag on the booking so we never double-send.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.booking import Booking
from app.models.asset import Asset
from app.models.customer import Customer
from app.core.logging import get_logger

log = get_logger("reminders")

# guest reminder text per language
G = {
    "hr": ("Podsjetnik na Vašu rezervaciju sutra",
           "Pozdrav,\n\nPodsjećamo Vas na Vašu rezervaciju sutra:\n\n{details}\n\nVeselimo se Vašem dolasku!\n\n{business}"),
    "en": ("Reminder: your booking tomorrow",
           "Hello,\n\nA friendly reminder about your booking tomorrow:\n\n{details}\n\nWe look forward to seeing you!\n\n{business}"),
    "de": ("Erinnerung: Ihre Buchung morgen",
           "Hallo,\n\neine freundliche Erinnerung an Ihre Buchung morgen:\n\n{details}\n\nWir freuen uns auf Sie!\n\n{business}"),
}


def _guest_msg(lang):
    return G.get((lang or "en").lower()[:2], G["en"])


def find_tomorrow_bookings(db: Session):
    """Confirmed bookings starting in the next 24-48h that haven't been reminded."""
    now = datetime.now(timezone.utc)
    start_win = now + timedelta(hours=12)
    end_win = now + timedelta(hours=36)
    rows = db.query(Booking).filter(
        Booking.status == "confirmed",
        Booking.reminder_sent == False,  # noqa: E712
        Booking.start_datetime >= start_win,
        Booking.start_datetime <= end_win,
    ).all()
    return rows


def send_reminders(db: Session, manager=None, business_name="Rentora") -> dict:
    """Send owner summary + guest reminders. Returns counts."""
    from app.integrations.email_imap import MultiMailboxManager
    if manager is None:
        manager = MultiMailboxManager.from_db(db)

    bookings = find_tomorrow_bookings(db)
    if not bookings:
        return {"owner": 0, "guests": 0, "bookings": 0}

    owner_lines = []
    guest_count = 0
    from_box = next(iter(manager.services.keys()), "") if manager.enabled else ""
    # Collect bookings per partner (external owner) for their own reminders.
    partner_bookings = {}   # owner_email -> {"name":, "lines":[]}

    for b in bookings:
        asset = db.get(Asset, b.asset_id)
        cust = db.get(Customer, b.customer_id)
        when = b.start_datetime.strftime("%d.%m.%Y %H:%M")
        aname = asset.name if asset else "—"
        pax = f" — {b.passengers} osoba" if getattr(b, "passengers", 0) else ""
        details = (f"• {when} — {aname}{pax}"
                   f"{(' — ' + (b.package_name or '')) if b.package_name else ''}"
                   f"{(' — ' + cust.full_name) if cust and cust.full_name else ''}")
        # For partner (external) boats: settlement line + queue a partner reminder.
        if asset and getattr(asset, "is_external", False):
            from app.services.external_service import settlement
            st = settlement(b.total_price or 0,
                            asset.commission_percent or 0,
                            getattr(asset, "payment_direction", "you"))
            owner = asset.owner_name or "partner"
            details += (f"\n    ↳ PARTNER ({owner}): {st['summary']}")
            if asset.owner_email:
                pb = partner_bookings.setdefault(
                    asset.owner_email, {"name": owner, "lines": []})
                # partner sees their boat, time, party size, settlement AND the
                # guest's name + phone (like Viator/GYG) so they can coordinate.
                gname = cust.full_name if (cust and cust.full_name
                                           and cust.full_name != (cust.email or "")) else ""
                gphone = cust.phone if (cust and cust.phone) else ""
                contact = ""
                if gname or gphone:
                    contact = f"\n    Gost: {gname or '—'}, tel: {gphone or '—'}"
                pb["lines"].append(
                    f"• {when} — {aname}{pax}{contact}\n    {st['summary']}")
        owner_lines.append(details)

        # guest reminder — sent from the mailbox assigned to this asset's type
        if manager.enabled and cust and cust.email:
            gbox = manager.box_for_type(asset.asset_type if asset else "") or from_box
            subj, tmpl = _guest_msg(cust.language)
            gdetails = f"{aname}\n{when}"
            if b.package_name:
                gdetails += f"\n{b.package_name}"
            body = tmpl.format(details=gdetails, business=business_name)
            manager.reply_from(gbox, cust.email, subj, body)
            guest_count += 1

        b.reminder_sent = True

    db.commit()

    # owner summary (one email listing ALL tomorrow's tours) — to you
    owner_sent = 0
    if manager.enabled and from_box and owner_lines:
        summary = ("Sutrašnje ture:\n\n" + "\n".join(owner_lines) +
                   f"\n\nUkupno: {len(owner_lines)}")
        manager.reply_from(from_box, from_box,
                           f"[PODSJETNIK] Sutrašnje ture ({len(owner_lines)})", summary)
        owner_sent = 1

    # per-partner reminders — each partner gets only THEIR bookings
    partner_sent = 0
    if manager.enabled:
        for owner_email, pb in partner_bookings.items():
            # boats default to the boat mailbox; fine for partner notices
            pbox = manager.box_for_type("boat") or from_box
            body = (f"Pozdrav {pb['name']},\n\nsutrašnje rezervacije za vaše plovilo:\n\n"
                    + "\n".join(pb["lines"]) +
                    "\n\nMolimo potvrdite da je sve u redu. Hvala na suradnji!")
            manager.reply_from(pbox, owner_email,
                               f"[PODSJETNIK] Sutrašnje rezervacije ({len(pb['lines'])})",
                               body)
            partner_sent += 1

    log.info("reminders_sent", owner=owner_sent, guests=guest_count,
             partners=partner_sent, bookings=len(bookings))
    return {"owner": owner_sent, "guests": guest_count, "partners": partner_sent,
            "bookings": len(bookings)}
