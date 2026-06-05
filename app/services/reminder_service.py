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

    for b in bookings:
        asset = db.get(Asset, b.asset_id)
        cust = db.get(Customer, b.customer_id)
        when = b.start_datetime.strftime("%d.%m.%Y %H:%M")
        aname = asset.name if asset else "—"
        details = (f"• {when} — {aname}"
                   f"{(' — ' + (b.package_name or '')) if b.package_name else ''}"
                   f"{(' — ' + cust.full_name) if cust and cust.full_name else ''}")
        owner_lines.append(details)

        # guest reminder
        if manager.enabled and cust and cust.email:
            subj, tmpl = _guest_msg(cust.language)
            gdetails = f"{aname}\n{when}"
            if b.package_name:
                gdetails += f"\n{b.package_name}"
            body = tmpl.format(details=gdetails, business=business_name)
            manager.reply_from(from_box, cust.email, subj, body)
            guest_count += 1

        b.reminder_sent = True

    db.commit()

    # owner summary (one email listing all tomorrow's tours)
    owner_sent = 0
    if manager.enabled and from_box and owner_lines:
        summary = ("Sutrašnje ture:\n\n" + "\n".join(owner_lines) +
                   f"\n\nUkupno: {len(owner_lines)}")
        manager.reply_from(from_box, from_box,
                           f"[PODSJETNIK] Sutrašnje ture ({len(owner_lines)})", summary)
        owner_sent = 1

    log.info("reminders_sent", owner=owner_sent, guests=guest_count,
             bookings=len(bookings))
    return {"owner": owner_sent, "guests": guest_count, "bookings": len(bookings)}
