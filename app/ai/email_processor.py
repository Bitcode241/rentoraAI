"""Detect email intent and auto-process via the AI agent.

Multilingual keyword detection (English, Croatian, German). The AI agent is the
real brain; these keywords only pre-tag the thread for the dashboard.
Respects settings.ai_auto_send and the agent's needs_human escalation.
"""
import re
from sqlalchemy.orm import Session
from app.models.email import EmailThread, EmailMessage
from app.models.booking import Booking
from app.services import conversation_service
from app.integrations.email_service import email_service
from app.ai.agent import run_agent
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("email-processor")

import re as _re
import threading

# Prevents the scheduler poll and a manual /api/emails/process call from
# processing the same mail at the same time (which caused double-processing
# and "lost" replies). Only one run executes at a time; the other skips.
_processing_lock = threading.Lock()

# A rental inquiry must mention one of OUR PRODUCTS. These are matched as whole
# words (so "book" won't match "Facebook", "transfer" won't match generic emails
# unless it's about a transfer service in a rental context).
PRODUCT_KW = [
    "boat", "boats", "jet ski", "jetski", "jet-ski", "yacht", "speedboat",
    "brod", "brodom", "broda", "gliser", "glisera", "skuter", "plovilo",
    "boot", "boote",
]
# Rental intent words — only count when a product is ALSO present (or a very
# strong standalone rental phrase below).
RENTAL_SIGNAL_KW = [
    "rent", "hire", "charter", "available", "availability", "book a", "booking",
    "reservation", "reserve",
    "najam", "iznajmiti", "iznajmljujete", "rezervacij", "rezervirati",
    "slobodno", "slobodan", "dostupno", "dostupan", "termin", "cijena", "cijenu",
    "mieten", "buchen", "verfügbar", "reservierung",
]
# Strong standalone phrases that ARE a rental inquiry even without a product word.
STRONG_REQUEST_KW = [
    "rent a boat", "rent a jet ski", "boat rental", "jet ski rental",
    "iznajmljivanje broda", "najam broda", "najam plovila", "zanima me najam",
    "želim rezervirati", "trebam brod", "trebam gliser", "boot mieten",
    "private transfer", "airport transfer", "transfer from", "transfer to",
    "transfer iz", "transfer do", "transfer za", "transfer od", "prijevoz",
    "transfer aerodrom", "aerodrom", "zračna luka", "flughafentransfer",
    "transfer s aerodroma", "transfer do aerodroma", "pickup from",
]


def _has_word(text: str, words) -> bool:
    for w in words:
        if " " in w or "-" in w:
            if w in text:
                return True
        else:
            if _re.search(r"\b" + _re.escape(w) + r"\b", text):
                return True
    return False


CONFIRM_KW = [
    "yes please", "go ahead", "i confirm the booking", "confirm my booking",
    "confirm the reservation", "potvrđujem rezervaciju", "potvrda rezervacije",
    "prihvaćam rezervaciju", "buchung bestätigen",
    # short but clear confirmations (used in reply to our quote)
    "potvrđujem", "može, potvrđujem", "slažem se", "ich bestätige",
]
CANCEL_KW = [
    "cancel my booking", "cancel the booking", "cancel my reservation",
    "cancel the reservation", "can't make", "cannot make",
    "otkazati rezervaciju", "otkazujem rezervaciju", "ne mogu doći",
    "otkaz rezervacije", "stornieren", "buchung absagen",
    # short but clear cancellations
    "moram otkazati", "želim otkazati", "otkazujem", "cancel booking",
]


def detect_intent(text: str) -> str:
    t = (text or "").lower()
    # cancellation / confirmation use specific phrases (not single words) so
    # "confirm your email" or "accept terms" no longer trigger.
    if _has_word(t, CANCEL_KW):
        return "cancellation"
    if _has_word(t, CONFIRM_KW):
        return "confirmation"
    # strong standalone rental phrases
    if _has_word(t, STRONG_REQUEST_KW):
        return "request"
    # otherwise require a PRODUCT word AND a rental signal together
    if _has_word(t, PRODUCT_KW) and _has_word(t, RENTAL_SIGNAL_KW):
        return "request"
    return "other"


# Intents the AI is ALLOWED to auto-reply to. Everything else is left for a human.
RENTAL_INTENTS = ("request", "confirmation", "cancellation")

# Senders the AI must NEVER auto-reply to (system / automated / no-reply).
# Replying to these can create mail loops and hurt server reputation.
BLOCKED_SENDER_PATTERNS = [
    "mailer-daemon", "postmaster", "no-reply", "noreply", "no_reply",
    "donotreply", "do-not-reply", "bounce", "notifications@", "notification@",
    "automated", "auto-reply", "autoreply", "daemon@", "abuse@", "root@",
]

# Subjects that signal an automated/system message (not a guest inquiry).
BLOCKED_SUBJECT_PATTERNS = [
    "undelivered mail", "returned to sender", "delivery status",
    "delivery failure", "mail delivery failed", "out of office",
    "automatic reply", "read receipt", "failure notice",
]


def _is_system_sender(sender_email: str, subject: str) -> bool:
    s = (sender_email or "").lower()
    subj = (subject or "").lower()
    if any(p in s for p in BLOCKED_SENDER_PATTERNS):
        return True
    if any(p in subj for p in BLOCKED_SUBJECT_PATTERNS):
        return True
    return False


def _extract_email(addr: str) -> str:
    m = re.search(r"[\w.\-+]+@[\w.\-]+", addr or "")
    return m.group(0) if m else ""


def _maybe_handle_owner_reply(db, sender_email, em, mailbox, manager):
    """If sender is an external owner with a pending request, process DA/NE.
    Returns a result dict if handled, else None."""
    from app.services import external_service, booking_service
    from app.models.external_request import ExternalRequest
    from app.models.asset import Asset
    from app.models.customer import Customer

    # token in subject/body like (referenca: A1B2C3)
    text = (em.get("subject", "") + " " + em.get("body", ""))
    m = re.search(r"\b([0-9A-F]{6})\b", text.upper())
    token = m.group(1) if m else ""

    req = external_service.find_open_request_for_owner(db, sender_email, token)
    if not req:
        return None  # not an owner reply — let normal flow handle it

    answer = external_service.parse_owner_reply(em.get("body", ""))
    if answer is None:
        # owner wrote something unclear — leave for human, don't guess
        log.info("external_owner_reply_unclear", req_id=req.id, sender=sender_email)
        return {"external_request": req.id, "owner_reply": "unclear",
                "needs_human": True, "auto_sent": False}

    asset = db.get(Asset, req.asset_id)
    guest = db.get(Customer, req.customer_id)

    if answer == "no":
        req.status = "declined"
        db.commit()
        # tell the guest it's not available
        if manager and guest and guest.email:
            manager.reply_from(req.guest_mailbox or mailbox, guest.email,
                               "Re: Upit za plovilo",
                               "Pozdrav,\n\nNažalost, plovilo nije slobodno za traženi "
                               "termin. Rado ću predložiti alternativu ako želite — "
                               "javite mi datum ili broj osoba pa provjerim druge opcije.\n\nLijep pozdrav")
        log.info("external_declined", req_id=req.id)
        return {"external_request": req.id, "owner_reply": "no",
                "needs_human": False, "auto_sent": True}

    # answer == "yes": create the booking, notify guest + business owner
    try:
        booking = booking_service.create_booking(
            db, asset_id=req.asset_id, customer_id=req.customer_id,
            package_id=req.package_id or None,
            start=req.start_datetime, end=req.end_datetime,
            source="external")
    except Exception as e:  # availability clash etc.
        log.warning("external_booking_failed", req_id=req.id, error=str(e))
        req.status = "confirmed"
        db.commit()
        return {"external_request": req.id, "owner_reply": "yes",
                "booking_error": str(e), "needs_human": True, "auto_sent": False}

    req.status = "confirmed"
    db.commit()

    split = external_service.commission_split(req.quoted_price,
                                              asset.commission_percent)
    # notify guest (from the mailbox they used)
    if manager and guest and guest.email:
        when = req.start_datetime.strftime("%d.%m.%Y %H:%M")
        manager.reply_from(req.guest_mailbox or mailbox, guest.email,
                           "Re: Potvrda rezervacije",
                           f"Pozdrav,\n\nVaš termin je potvrđen!\n\n"
                           f"Plovilo: {asset.name}\nTermin: {when}\n"
                           f"Cijena: {split['guest_pays']} EUR\n\n"
                           f"Uskoro šaljem detalje za dovršetak rezervacije.\n\nLijep pozdrav")
    # notify the business owner (you) — to the mailbox that received it
    if manager:
        manager.reply_from(mailbox, mailbox,
                           f"[INTERNO] Vanjski brod potvrđen: {asset.name}",
                           f"Vlasnik je potvrdio {asset.name}.\n"
                           f"Gost: {req.guest_email}\n"
                           f"Cijena gostu: {split['guest_pays']} EUR\n"
                           f"Tvoja provizija: {split['your_commission']} EUR\n"
                           f"Vlasniku ide: {split['owner_gets']} EUR\n"
                           f"Booking #{booking.id}")
    log.info("external_confirmed", req_id=req.id, booking_id=booking.id)
    return {"external_request": req.id, "owner_reply": "yes",
            "booking_id": booking.id, "needs_human": False, "auto_sent": True}


def process_unread(db: Session, max_results: int = 10) -> list:
    # If another run is already in progress, skip — avoids double-processing.
    if not _processing_lock.acquire(blocking=False):
        log.info("email_processing_skipped_locked")
        return []
    try:
        return _process_unread_inner(db, max_results)
    finally:
        _processing_lock.release()


def _process_unread_inner(db: Session, max_results: int = 10) -> list:
    from app.integrations.email_imap import MultiMailboxManager
    mailbox_manager = MultiMailboxManager.from_db(db)
    processed = []
    if mailbox_manager.enabled:
        inbox = mailbox_manager.list_all_unread(max_per_box=max_results)
        use_manager = True
    else:
        inbox = email_service.list_unread(max_results=max_results)
        use_manager = False

    for em in inbox:
        sender_email = em.get("from_email") or _extract_email(em.get("from", ""))
        mailbox = em.get("mailbox", "")   # which of our addresses received it

        # --- EXTERNAL OWNER REPLY? (check before the rental filter) ---
        # If this sender is the owner of an external asset AND has a pending
        # request, treat their DA/NE as an availability answer, not a guest mail.
        handled = _maybe_handle_owner_reply(db, sender_email, em, mailbox,
                                            mailbox_manager if use_manager else None)
        if handled is not None:
            if use_manager:
                mailbox_manager.mark_read(mailbox, em.get("id", ""))
            processed.append(handled)
            continue

        customer = conversation_service.find_or_create_customer(
            db, email=sender_email, full_name=sender_email)

        thread_key = em.get("thread_id") or em.get("id")
        thread = db.query(EmailThread).filter(
            EmailThread.gmail_thread_id == thread_key).first()
        intent = detect_intent(em.get("subject", "") + " " + em.get("body", ""))

        # SAFETY FILTER (before any AI call): reply ONLY to genuine rental
        # inquiries. System/automated senders and non-rental mail are left
        # completely untouched for the owner — no reply, no wasted AI call.
        is_system = _is_system_sender(sender_email, em.get("subject", ""))
        is_rental = intent in RENTAL_INTENTS

        # If this sender already has a conversation/booking with us, treat their
        # follow-up as part of that rental conversation even if the strict keyword
        # filter says "other" (e.g. short replies like "yes, book it" or
        # "can I get that one?"). This prevents dropping genuine follow-ups.
        is_known_guest = False
        if not is_system:
            existing_thread = db.query(EmailThread).filter(
                EmailThread.customer_id == customer.id).first()
            existing_booking = db.query(Booking).filter(
                Booking.customer_id == customer.id).first()
            is_known_guest = bool(existing_thread or existing_booking)

        if is_system or (not is_rental and not is_known_guest):
            if is_system and use_manager:
                mailbox_manager.mark_read(mailbox, em.get("id", ""))
            log.info("email_ignored", mailbox=mailbox, intent=intent,
                     is_system=is_system, sender=sender_email)
            processed.append({"customer_id": customer.id, "intent": intent,
                              "mailbox": mailbox, "ignored": True,
                              "reason": "system_sender" if is_system else "not_rental",
                              "auto_sent": False})
            continue
        if not is_rental and is_known_guest:
            # follow-up from someone we're already talking to — let the AI handle it
            intent = "request"
            log.info("email_followup_known_guest", sender=sender_email)

        if not thread:
            thread = EmailThread(gmail_thread_id=thread_key,
                                 subject=em.get("subject", ""),
                                 customer_id=customer.id, intent=intent)
            db.add(thread)
            db.commit()
            db.refresh(thread)

        db.add(EmailMessage(thread_id=thread.id, gmail_message_id=em.get("id", ""),
                            sender=em.get("from", ""), recipient=em.get("to", ""),
                            subject=em.get("subject", ""), body=em.get("body", ""),
                            direction="inbound"))
        db.commit()
        conversation_service.add_message(db, customer.id, "email", "inbound",
                                         em.get("body", ""))

        result = run_agent(db, em.get("body", ""), language=customer.language,
                           customer_id=customer.id)

        auto = settings.ai_auto_send and not result["needs_human"] and result["reply"]
        if auto:
            subject = f"Re: {em.get('subject', '')}"
            if use_manager:
                # reply FROM the address that received the message
                mailbox_manager.reply_from(mailbox, sender_email, subject,
                                           result["reply"], thread_id=em.get("in_reply_to", ""))
            else:
                email_service.send(sender_email, subject, result["reply"],
                                   thread_id=em.get("in_reply_to", ""))
            conversation_service.add_message(db, customer.id, "email", "outbound",
                                             result["reply"])
            thread.intent = intent
            db.commit()
        else:
            conv = conversation_service.get_or_create_conversation(db, customer.id)
            conv.needs_human = True
            db.commit()
            if result["reply"]:
                conversation_service.add_message(
                    db, customer.id, "email", "outbound",
                    "[DRAFT — awaiting human review] " + result["reply"])

        if use_manager:
            mailbox_manager.mark_read(mailbox, em.get("id", ""))
        else:
            email_service.mark_read(em.get("id", ""))
        processed.append({"customer_id": customer.id, "intent": intent,
                          "mailbox": mailbox,
                          "needs_human": result["needs_human"],
                          "auto_sent": bool(auto)})
    log.info("emails_processed", count=len(processed))
    return processed
