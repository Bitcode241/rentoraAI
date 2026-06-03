from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.email import EmailThread, EmailMessage
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.ai.email_processor import process_unread
from app.integrations.email_service import email_service
from app.core.config import settings

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("/threads")
def list_threads(db: Session = Depends(get_db), _=Depends(get_current_user)):
    threads = db.query(EmailThread).order_by(EmailThread.updated_at.desc()).all()
    return [{"id": t.id, "subject": t.subject, "intent": t.intent,
             "customer_id": t.customer_id,
             "messages": db.query(EmailMessage).filter(
                 EmailMessage.thread_id == t.id).count()} for t in threads]


@router.get("/threads/{thread_id}")
def get_thread(thread_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    msgs = db.query(EmailMessage).filter(EmailMessage.thread_id == thread_id)\
        .order_by(EmailMessage.created_at).all()
    return [{"sender": m.sender, "subject": m.subject, "body": m.body,
             "direction": m.direction, "created_at": m.created_at} for m in msgs]


@router.post("/process")
def process_inbox(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return {"processed": process_unread(db)}


@router.get("/status")
def email_status(_=Depends(get_current_user)):
    """Show which email provider is active and scheduler config."""
    return {
        "email_enabled": getattr(email_service, "enabled", False),
        "provider": email_service.__class__.__name__,
        "scheduler_enabled": settings.scheduler_enabled,
        "poll_seconds": settings.email_poll_seconds,
        "ai_auto_send": settings.ai_auto_send,
        "ai_active": bool(settings.openai_api_key),
    }


@router.get("/needs-human")
def needs_human(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Conversations the AI escalated for human review."""
    convs = db.query(Conversation).filter(Conversation.needs_human.is_(True))\
        .order_by(Conversation.updated_at.desc()).all()
    out = []
    for c in convs:
        cust = db.get(Customer, c.customer_id)
        out.append({"conversation_id": c.id, "customer_id": c.customer_id,
                    "customer_name": cust.full_name if cust else "",
                    "last_channel": c.last_channel})
    return out


@router.post("/needs-human/{customer_id}/resolve")
def resolve(customer_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    conv = db.query(Conversation).filter(
        Conversation.customer_id == customer_id).first()
    if conv:
        conv.needs_human = False
        db.commit()
    return {"resolved": customer_id}
