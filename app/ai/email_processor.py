"""Detect email intent and auto-process via the AI agent.

Multilingual keyword detection (English, Croatian, German). The AI agent is the
real brain; these keywords only pre-tag the thread for the dashboard.
Respects settings.ai_auto_send and the agent's needs_human escalation.
"""
import re
from sqlalchemy.orm import Session
from app.models.email import EmailThread, EmailMessage
from app.services import conversation_service
from app.integrations.email_service import email_service
from app.ai.agent import run_agent
from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("email-processor")

REQUEST_KW = [
    # en
    "rent", "book", "available", "availability", "reservation", "quote", "hire",
    # hr
    "najam", "najmiti", "iznajmiti", "rezervacija", "rezervirati", "slobodno",
    "dostupno", "cijena", "ponuda", "termin",
    # de
    "mieten", "buchen", "verfügbar", "reservierung", "angebot", "preis",
]
CONFIRM_KW = [
    "confirm", "yes please", "go ahead", "i confirm", "accept",
    "potvrđujem", "potvrda", "slažem se", "može", "u redu", "prihvaćam",
    "bestätige", "bestätigung", "einverstanden",
]
CANCEL_KW = [
    "cancel", "refund", "can't make", "cannot make",
    "otkaz", "otkazati", "otkazujem", "ne mogu doći", "povrat",
    "stornieren", "absagen", "rückerstattung",
]


def detect_intent(text: str) -> str:
    t = (text or "").lower()
    if any(k in t for k in CANCEL_KW):
        return "cancellation"
    if any(k in t for k in CONFIRM_KW):
        return "confirmation"
    if any(k in t for k in REQUEST_KW):
        return "request"
    return "other"


def _extract_email(addr: str) -> str:
    m = re.search(r"[\w.\-+]+@[\w.\-]+", addr or "")
    return m.group(0) if m else ""


def process_unread(db: Session, max_results: int = 10) -> list:
    processed = []
    for em in email_service.list_unread(max_results=max_results):
        sender_email = em.get("from_email") or _extract_email(em.get("from", ""))
        customer = conversation_service.find_or_create_customer(
            db, email=sender_email, full_name=sender_email)

        thread_key = em.get("thread_id") or em.get("id")
        thread = db.query(EmailThread).filter(
            EmailThread.gmail_thread_id == thread_key).first()
        intent = detect_intent(em.get("subject", "") + " " + em.get("body", ""))
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

        # Escalation gate: only auto-send when allowed AND the agent is confident.
        auto = settings.ai_auto_send and not result["needs_human"] and result["reply"]
        if auto:
            email_service.send(sender_email, f"Re: {em.get('subject', '')}",
                               result["reply"], thread_id=em.get("in_reply_to", ""))
            conversation_service.add_message(db, customer.id, "email", "outbound",
                                             result["reply"])
            thread.intent = intent
            db.commit()
        else:
            # Hold for human: flag the conversation, store the draft as metadata.
            conv = conversation_service.get_or_create_conversation(db, customer.id)
            conv.needs_human = True
            db.commit()
            if result["reply"]:
                conversation_service.add_message(
                    db, customer.id, "email", "outbound",
                    "[DRAFT — awaiting human review] " + result["reply"])

        email_service.mark_read(em.get("id", ""))
        processed.append({"customer_id": customer.id, "intent": intent,
                          "needs_human": result["needs_human"],
                          "auto_sent": bool(auto)})
    log.info("emails_processed", count=len(processed))
    return processed
