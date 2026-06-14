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
    "boot", "boote", "barracuda", "atlantic", "gaia", "marine", "yamaha",
    "tour", "excursion", "izlet", "krstaren", "transfer", "prijevoz",
]
# Rental intent words — only count when a product is ALSO present (or a very
# strong standalone rental phrase below).
RENTAL_SIGNAL_KW = [
    "rent", "hire", "charter", "available", "availability", "book a", "booking",
    "reservation", "reserve",
    "najam", "iznajmiti", "iznajmljujete", "rezervacij", "rezervirati",
    "slobodno", "slobodan", "slobodna", "dostupno", "dostupan", "dostupna",
    "raspoloživ", "raspolozivo", "raspolaze", "raspolažete",
    "termin", "cijena", "cijenu", "cijene", "kosta", "košta", "koliko",
    "imate li", "imate", "možete li", "mozete li", "zanima me", "zanima nas",
    "interested", "interested in", "do you have", "can i", "could i", "would like",
    "mieten", "buchen", "verfügbar", "reservierung", "preis", "kostet",
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


def _detect_language(text: str, fallback: str = "en") -> str:
    """Guess the guest's language from their message so we reply in the same one.
    Lightweight keyword check for Croatian and German; defaults to English."""
    t = (text or "").lower()
    hr = ["pozdrav", "molim", "hvala", "zanima", "imate", "slobod", "brod",
          "može", "trebam", "želim", "koliko", "cijena", "dostupno", "lijep pozdrav",
          "osoba", "ljudi", "termin", "rezervacij", "najam"]
    de = ["hallo", "guten", "danke", "bitte", "verfügbar", "boot", "ich möchte",
          "buchen", "preis", "kostet", "personen", "mieten", "grüße"]
    hr_hits = sum(1 for w in hr if w in t)
    de_hits = sum(1 for w in de if w in t)
    if hr_hits >= 1 and hr_hits >= de_hits:
        return "hr"
    if de_hits >= 1:
        return "de"
    return fallback or "en"


def _transfer_checking_reply(language: str) -> str:
    """Tell the guest we're confirming the transfer price (route not in our table)."""
    lang = (language or "en").lower()[:2]
    if lang == "hr":
        return ("Pozdrav,\n\nHvala na upitu za transfer! Provjeravam točnu cijenu za "
                "Vašu rutu i javljam se vrlo brzo s potvrdom.\n\nLijep pozdrav!")
    if lang == "de":
        return ("Hallo,\n\nvielen Dank für Ihre Transfer-Anfrage! Ich prüfe den "
                "genauen Preis für Ihre Strecke und melde mich in Kürze.\n\n"
                "Beste Grüße!")
    return ("Hello,\n\nThanks for your transfer request! I'm confirming the exact "
            "price for your route and will get back to you very shortly.\n\n"
            "Best regards!")


def _notify_owner_transfer_price(db, mailbox, customer, tq, use_manager,
                                 mailbox_manager):
    """Email the business owner (you) to set a price for a transfer route the
    system couldn't price automatically."""
    dist = (f"{tq['distance_km']} km" if tq.get("distance_km") else "nepoznata")
    body = (f"Gost traži transfer koji sustav ne može automatski izračunati.\n\n"
            f"Gost: {customer.full_name or customer.email} ({customer.email})\n"
            f"Lokacija: {tq.get('location', '—')}\n"
            f"Udaljenost od baze: {dist}\n"
            f"Broj osoba: {tq.get('passengers', '—')}\n"
            f"Povratno: {'DA' if tq.get('round_trip') else 'NE'}\n"
            f"Razlog: {tq.get('reason', '—')}\n\n"
            f"Odredi cijenu i odgovori gostu, ili dodaj zonu u admin.")
    try:
        if use_manager:
            mailbox_manager.reply_from(mailbox, mailbox,
                                       "[CIJENA TRANSFERA] Treba tvoja cijena", body)
        log.info("owner_transfer_price_emailed", location=tq.get("location"))
    except Exception as e:
        log.warning("owner_transfer_email_failed", error=str(e))


def _checking_reply(language: str) -> str:
    """Professional 'we're checking availability' message. Used when the chosen
    boat is a partner boat and we've asked the owner in the background — the guest
    should NOT know a partner is involved."""
    lang = (language or "en").lower()[:2]
    if lang == "hr":
        return ("Pozdrav,\n\nHvala na upitu! Trenutno provjeravam dostupnost za "
                "traženi termin i javljam Vam se u najkraćem mogućem roku s "
                "potvrdom i svim detaljima.\n\n"
                "Kako bismo ubrzali rezervaciju, molim Vas pošaljite:\n"
                "• Ime i prezime\n"
                "• Broj telefona (WhatsApp/Viber)\n"
                "• Trebate li transfer (prijevoz do plovila)? Polazak je iz Gruža "
                "ili s Lapada.\n\nLijep pozdrav!")
    if lang == "de":
        return ("Hallo,\n\nvielen Dank für Ihre Anfrage! Ich prüfe gerade die "
                "Verfügbarkeit und melde mich schnellstmöglich mit einer "
                "Bestätigung.\n\nUm die Buchung zu beschleunigen, senden Sie bitte:\n"
                "• Vor- und Nachname\n"
                "• Telefonnummer (WhatsApp/Viber)\n"
                "• Benötigen Sie einen Transfer zum Boot? Abfahrt ab Gruž oder "
                "Lapad.\n\nBeste Grüße!")
    return ("Hello,\n\nThank you for your inquiry! I'm checking availability and "
            "will get back to you very shortly with confirmation.\n\n"
            "To speed up your booking, please send us:\n"
            "• Full name\n"
            "• Phone number (WhatsApp/Viber)\n"
            "• Do you need a transfer (ride to the boat)? Departure from Gruž or "
            "Lapad.\n\nBest regards!")


def detect_intent(text: str) -> str:
    t = (text or "").lower()
    # Marketing / B2B sales pitches often mention "boat/yacht" but are NOT guest
    # inquiries. If it smells like a sales pitch, treat as 'other' (ignore).
    SPAM_KW = [
        "easymls", "mls", "import your listings", "yachting professionals",
        "boost your sales", "grow your business", "our platform", "our software",
        "increase your bookings", "list your", "sign up", "free trial",
        "marketing", "seo", "lead generation", "newsletter", "unsubscribe",
        "partnership opportunity", "affiliate", "we help businesses",
        "as a professional in boat", "yacht sales",
    ]
    if any(k in t for k in SPAM_KW):
        return "other"
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
        # No clear yes/no AND no token referencing the request → this probably
        # isn't an owner reply at all (e.g. the same person emailing as a guest).
        # Fall through to normal handling instead of parking it for a human.
        if not token:
            return None
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

    # Safety net: a partner boat may have no package/deposit set, which would leave
    # deposit at 0 and block the payment link. Fall back to the global default %.
    if (not booking.deposit_amount or booking.deposit_amount <= 0):
        from app.services import settings_service
        total = booking.total_price or req.quoted_price or 0
        pct = settings_service.default_deposit_percent(db)
        if total > 0:
            booking.total_price = booking.total_price or total
            booking.deposit_amount = round(total * pct / 100.0, 2)
            db.commit()
            log.info("external_deposit_fallback", booking_id=booking.id,
                     deposit=booking.deposit_amount)

    split = external_service.commission_split(req.quoted_price,
                                              asset.commission_percent)
    # Owner said YES → send the guest the DEPOSIT LINK immediately, so you don't
    # have to do anything. One step: owner confirms, guest pays.
    from app.services import payment_service
    from app.ai.agent import _deposit_reply
    from app.core.timeutil import fmt_local
    pay = payment_service.create_deposit_checkout(
        booking, asset.name, guest_email=req.guest_email or "")
    when = fmt_local(req.start_datetime)
    if manager and guest and guest.email:
        if pay.get("url"):
            body = _deposit_reply(guest.language or "hr", {
                "asset_name": asset.name, "when": when,
                "deposit_amount": booking.deposit_amount,
                "total_price": booking.total_price,
                "payment_url": pay["url"]})
        else:
            # Stripe couldn't make a link (e.g. deposit 0) — confirm and flag you.
            body = (f"Pozdrav,\n\nVaš termin za {asset.name} ({when}) je potvrđen!\n"
                    f"Uskoro šaljem detalje za uplatu.\n\nLijep pozdrav")
        manager.reply_from(req.guest_mailbox or mailbox, guest.email,
                           "Re: Potvrda rezervacije", body)
    # notify the business owner (you) — to the mailbox that received it
    if manager:
        manager.reply_from(mailbox, mailbox,
                           f"[INTERNO] Vanjski brod potvrđen: {asset.name}",
                           f"Vlasnik je potvrdio {asset.name}.\n"
                           f"Gost: {req.guest_email}\n"
                           f"Cijena gostu: {split['guest_pays']} EUR\n"
                           f"Tvoja provizija: {split['your_commission']} EUR\n"
                           f"Vlasniku ide: {split['owner_gets']} EUR\n"
                           f"Link gostu poslan: {'DA' if pay.get('url') else 'NE — provjeri depozit'}\n"
                           f"Booking #{booking.id}")
    log.info("external_confirmed", req_id=req.id, booking_id=booking.id,
             link_sent=bool(pay.get("url")))
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


def _send_or_draft(db, conv_id, thread, mailbox, sender_email, em, reply_text,
                   settings, use_manager, mailbox_manager, email_service, intent):
    """Send a ready-made reply (e.g. the 'checking availability' message) the same
    way the main flow does, and mark the email read. Always auto-sends when
    AI_AUTO_SEND is on, since this text is safe and code-generated."""
    from app.models.email import EmailMessage
    subject = f"Re: {em.get('subject', '')}"
    reply_ref = em.get("message_id", "") or em.get("in_reply_to", "")
    if settings.ai_auto_send:
        if use_manager:
            mailbox_manager.reply_from(mailbox, sender_email, subject,
                                       reply_text, thread_id=reply_ref)
        else:
            email_service.send(sender_email, subject, reply_text, thread_id=reply_ref)
        conversation_service.add_message_to(db, conv_id, "email", "outbound", reply_text)
        db.add(EmailMessage(thread_id=thread.id, gmail_message_id="",
                            sender=mailbox, recipient=sender_email,
                            subject=subject, body=reply_text, direction="outbound"))
        thread.intent = intent
        db.commit()
    else:
        conversation_service.add_message_to(
            db, conv_id, "email", "outbound",
            "[DRAFT — awaiting human review] " + reply_text)
    if use_manager:
        mailbox_manager.mark_read(mailbox, em.get("id", ""))
    else:
        email_service.mark_read(em.get("id", ""))


def _process_unread_inner(db: Session, max_results: int = 10) -> list:
    from app.integrations.email_imap import MultiMailboxManager
    mailbox_manager = MultiMailboxManager.from_db(db)
    processed = []
    if mailbox_manager.enabled:
        inbox = mailbox_manager.list_all_unread(max_per_box=max_results)
        use_manager = True
        # Our own mailbox addresses — NEVER process mail that we ourselves sent,
        # otherwise the AI replies to its own messages in an endless loop.
        own_addresses = {a.lower() for a in mailbox_manager.services.keys()}
    else:
        inbox = email_service.list_unread(max_results=max_results)
        use_manager = False
        own_addresses = set()

    for em in inbox:
      try:
        sender_email = em.get("from_email") or _extract_email(em.get("from", ""))
        mailbox = em.get("mailbox", "")   # which of our addresses received it

        # Skip anything sent from one of our own addresses (self-sent / loops).
        if sender_email and sender_email.lower() in own_addresses:
            if use_manager:
                mailbox_manager.mark_read(mailbox, em.get("id", ""))
            log.info("email_skipped_self", sender=sender_email)
            continue

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

        sender_name = em.get("from_name") or ""
        customer = conversation_service.find_or_create_customer(
            db, email=sender_email, full_name=sender_name or sender_email)
        # If we learned a real display name and the stored one is still the email,
        # upgrade it so confirmations show a proper name.
        if sender_name and customer.full_name in ("", sender_email):
            customer.full_name = sender_name
            db.commit()

        # Reply in the language the guest actually wrote in (don't get stuck on a
        # stale stored language). Update it when we can tell.
        _lang = _detect_language(em.get("body", ""), fallback=customer.language or "en")
        if _lang and _lang != customer.language:
            customer.language = _lang
            db.commit()

        # --- THREAD RESOLUTION (judge same-thread vs new inquiry) ---
        # A reply carries In-Reply-To/References pointing at an earlier message.
        # A fresh inquiry has neither -> it's a NEW thread (even from the same
        # address), so an agency booking for many clients gets separate threads.
        refs = (em.get("in_reply_to", "") + " " + em.get("references", "")).strip()
        thread = None
        if refs:
            ref_ids = re.findall(r"<[^>]+>", refs)
            if ref_ids:
                thread = (db.query(EmailThread)
                          .join(EmailMessage, EmailMessage.thread_id == EmailThread.id)
                          .filter(EmailMessage.gmail_message_id.in_(ref_ids))
                          .first())
                if not thread:
                    thread = (db.query(EmailThread)
                              .filter(EmailThread.gmail_thread_id.in_(ref_ids))
                              .first())
        intent = detect_intent(em.get("subject", "") + " " + em.get("body", ""))

        # Fallback thread match: a reply whose headers we couldn't match (e.g. some
        # iPhone/Gmail replies) should still continue the guest's MOST RECENT thread
        # rather than starting a fresh one — otherwise the boat/date from the offer
        # is lost. Only do this when the message looks like a reply (has refs OR
        # quotes our previous mail), to avoid merging genuinely separate inquiries.
        if not thread:
            looks_like_reply = bool(refs) or ("wrote:" in (em.get("body", "") or "").lower()) \
                or ("> on " in (em.get("body", "") or "").lower()) \
                or (em.get("subject", "").lower().startswith("re:"))
            if looks_like_reply:
                recent = (db.query(EmailThread)
                          .filter(EmailThread.customer_id == customer.id)
                          .order_by(EmailThread.id.desc()).first())
                if recent:
                    thread = recent
                    log.info("thread_reattached_by_recency",
                             thread_id=recent.id, sender=sender_email)

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
            # Guard against a duplicate gmail_thread_id (same message seen twice,
            # or a reply whose id we already stored) — reuse instead of crashing.
            tid = em.get("message_id") or em.get("id")
            if tid:
                existing = (db.query(EmailThread)
                            .filter(EmailThread.gmail_thread_id == tid).first())
                if existing:
                    thread = existing
            if not thread:
                # brand-new inquiry -> its own thread AND its own conversation
                conv = conversation_service.create_conversation(db, customer.id)
                thread = EmailThread(gmail_thread_id=tid,
                                     subject=em.get("subject", ""),
                                     customer_id=customer.id, intent=intent,
                                     conversation_id=conv.id)
                db.add(thread)
                try:
                    db.commit()
                    db.refresh(thread)
                except Exception:
                    # Another concurrent insert won the race — roll back and reuse.
                    db.rollback()
                    thread = (db.query(EmailThread)
                              .filter(EmailThread.gmail_thread_id == tid).first())
                    if not thread:
                        raise
        conv_id = thread.conversation_id
        if not conv_id:
            # legacy thread without a conversation yet — attach one
            conv = conversation_service.create_conversation(db, customer.id)
            thread.conversation_id = conv.id
            db.commit()
            conv_id = conv.id

        db.add(EmailMessage(thread_id=thread.id, gmail_message_id=em.get("message_id") or em.get("id", ""),
                            sender=em.get("from", ""), recipient=em.get("to", ""),
                            subject=em.get("subject", ""), body=em.get("body", ""),
                            direction="inbound"))
        db.commit()
        conversation_service.add_message_to(db, conv_id, "email", "inbound",
                                            em.get("body", ""))

        # CODE COMPUTES THE FACTS (availability + prices) so the AI can't invent
        # boats or prices — it only phrases what the code found. Starts with boats.
        facts = ""
        # FIRST: if the guest named a model + date and the only available boat is a
        # PARTNER boat (yours out/busy), ask the owner NOW and tell the guest we're
        # checking — no "available but on request" confusion.
        try:
            from app.services import auto_deposit_service as _ad
            convo_now = "\n".join(
                m.body for m in conversation_service.history_for(db, conv_id, limit=20)) \
                if conv_id else em.get("body", "")
            inq = _ad.try_inquiry_chain(
                db, conversation_text=convo_now or em.get("body", ""),
                latest_message=em.get("body", ""),
                customer_id=customer.id, guest_mailbox=mailbox)
            if inq and inq.get("owner_asked"):
                reply_txt = _checking_reply(customer.language)
                _send_or_draft(db, conv_id, thread, mailbox, sender_email, em,
                               reply_txt, settings, use_manager, mailbox_manager,
                               email_service, intent)
                log.info("inquiry_chain_owner_asked_guest_notified",
                         customer_id=customer.id, asset=inq.get("asset"))
                processed.append({"customer_id": customer.id, "intent": intent,
                                  "mailbox": mailbox, "owner_asked": True,
                                  "auto_sent": True})
                continue
        except Exception as e:
            log.warning("inquiry_chain_failed", error=str(e))
        try:
            from app.services import inquiry_service
            if inquiry_service.wants_boats(em.get("body", ""), db=db):
                bf = inquiry_service.build_boat_availability(db, em.get("body", ""))
                facts = inquiry_service.facts_to_prompt(bf)
                if bf:
                    log.info("boat_facts_computed", available=bf.get("any_available"),
                             options=len(bf.get("options", [])))
        except Exception as e:
            log.warning("facts_failed", error=str(e))

        # TRANSFER: if the guest asked about a transfer, CODE prices it (GPS radius
        # or named zone). If the route is unknown, email the owner to set a price
        # and tell the guest we're checking — never invent a transfer price.
        try:
            from app.services import transfer_inquiry_service as tinq
            if tinq.wants_transfer(em.get("body", "")):
                tq = tinq.quote_for_message(db, em.get("body", ""))
                if tq.get("status") == "ok":
                    dline = (f" (~{tq['distance_km']} km)" if tq.get("distance_km")
                             else "")
                    dirtxt = ("povratno" if tq.get("direction") == "round_trip"
                              else "jednosmjerno")
                    facts += (f"\n[TRANSFER] Ruta: {tq['location']}{dline}. "
                              f"Cijena ({dirtxt}, {tq['passengers']} os.): "
                              f"{tq['price']} EUR. Departure Gruž ili Lapad. "
                              f"Use this transfer price verbatim.")
                    log.info("transfer_priced", location=tq["location"],
                             price=tq["price"])
                elif tq.get("status") == "needs_owner_price":
                    # ask the owner to set a price, notify the guest we're checking
                    _notify_owner_transfer_price(db, mailbox, customer, tq,
                                                 use_manager, mailbox_manager)
                    reply_txt = _transfer_checking_reply(customer.language)
                    _send_or_draft(db, conv_id, thread, mailbox, sender_email, em,
                                   reply_txt, settings, use_manager,
                                   mailbox_manager, email_service, intent)
                    log.info("transfer_owner_price_asked",
                             location=tq.get("location"))
                    processed.append({"customer_id": customer.id, "intent": intent,
                                      "mailbox": mailbox, "transfer_owner_asked": True,
                                      "auto_sent": True})
                    continue
        except Exception as e:
            log.warning("transfer_inquiry_failed", error=str(e))

        result = run_agent(db, em.get("body", ""), language=customer.language,
                           customer_id=customer.id, facts=facts)

        # If the code supplied availability facts, presenting them is a complete
        # answer — don't let a stray escalation hold it back as a draft.
        if facts and result.get("reply") and result.get("needs_human"):
            log.info("availability_answer_autosent")
            result["needs_human"] = False

        # CODE TAKES OVER THE MONEY STEP: scope the conversation text to THIS thread
        # so a different inquiry's boat/date never bleeds into this one.
        try:
            from app.services import auto_deposit_service
            from app.ai.agent import _deposit_reply
            convo = "\n".join(
                m.body for m in conversation_service.history_for(db, conv_id, limit=20))
            dep = auto_deposit_service.try_auto_deposit(
                db, conversation_text=convo, latest_message=em.get("body", ""),
                customer_id=customer.id, guest_mailbox=mailbox)
            if dep and dep.get("payment_url"):
                # Use the AI's text if it wrote one, otherwise a clean built reply,
                # and make sure the link is present in the outgoing message.
                base = result.get("reply") or ""
                if dep["payment_url"] not in base:
                    base = _deposit_reply(customer.language, dep)
                result = {"reply": base, "needs_human": False,
                          "actions": result.get("actions", [])}
                log.info("auto_deposit_sent", customer_id=customer.id,
                         booking_id=dep.get("booking_id"))
            elif dep and dep.get("owner_asked"):
                # Partner boat: we've asked the owner in the background. Tell the
                # guest we're checking availability — do NOT mention partners or
                # that we have to ask anyone. Clean, professional.
                result = {"reply": _checking_reply(customer.language),
                          "needs_human": False, "actions": []}
                log.info("chain_owner_asked_guest_notified",
                         customer_id=customer.id, asset=dep.get("asset"))
            elif dep and dep.get("error") == "not_available":
                log.info("auto_deposit_not_available", asset=dep.get("asset"))
        except Exception as e:
            log.warning("auto_deposit_failed", error=str(e))

        auto = settings.ai_auto_send and not result["needs_human"] and result["reply"]
        if auto:
            subject = f"Re: {em.get('subject', '')}"
            reply_ref = em.get("message_id", "") or em.get("in_reply_to", "")
            if use_manager:
                # reply FROM the address that received the message
                mailbox_manager.reply_from(mailbox, sender_email, subject,
                                           result["reply"], thread_id=reply_ref)
            else:
                email_service.send(sender_email, subject, result["reply"],
                                   thread_id=reply_ref)
            conversation_service.add_message_to(db, conv_id, "email", "outbound",
                                                result["reply"])
            db.add(EmailMessage(thread_id=thread.id, gmail_message_id="",
                                sender=mailbox, recipient=sender_email,
                                subject=subject, body=result["reply"],
                                direction="outbound"))
            thread.intent = intent
            db.commit()
        else:
            from app.models.conversation import Conversation as _Conv
            conv = db.get(_Conv, conv_id)
            if conv:
                conv.needs_human = True
                db.commit()
            if result["reply"]:
                conversation_service.add_message_to(
                    db, conv_id, "email", "outbound",
                    "[DRAFT — awaiting human review] " + result["reply"])

        if use_manager:
            mailbox_manager.mark_read(mailbox, em.get("id", ""))
        else:
            email_service.mark_read(em.get("id", ""))
        processed.append({"customer_id": customer.id, "intent": intent,
                          "mailbox": mailbox,
                          "needs_human": result["needs_human"],
                          "auto_sent": bool(auto)})
      except Exception as _e:
        db.rollback()
        log.warning("email_item_failed", error=str(_e),
                    sender=em.get("from", ""))
        continue
    log.info("emails_processed", count=len(processed))
    return processed
