"""Unified conversation history across email + WhatsApp."""
from sqlalchemy.orm import Session
from app.models.conversation import Conversation, Message
from app.models.customer import Customer


def get_or_create_conversation(db: Session, customer_id: int) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.customer_id == customer_id).first()
    if not conv:
        conv = Conversation(customer_id=customer_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def create_conversation(db: Session, customer_id: int) -> Conversation:
    """Always create a NEW conversation (used when a new email thread starts)."""
    conv = Conversation(customer_id=customer_id)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def add_message_to(db: Session, conversation_id: int, channel: str, direction: str,
                   body: str, meta: str = "") -> Message:
    """Add a message to a SPECIFIC conversation (scoped to one email thread)."""
    conv = db.get(Conversation, conversation_id)
    if conv:
        conv.last_channel = channel
    msg = Message(conversation_id=conversation_id, channel=channel,
                  direction=direction, body=body, meta=meta)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def history_for(db: Session, conversation_id: int, limit: int = 30):
    """History for a SPECIFIC conversation only (one thread, not all the
    customer's mail). Keeps separate inquiries from bleeding into each other."""
    return (db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit).all())


def add_message(db: Session, customer_id: int, channel: str, direction: str,
                body: str, meta: str = "") -> Message:
    conv = get_or_create_conversation(db, customer_id)
    conv.last_channel = channel
    msg = Message(conversation_id=conv.id, channel=channel,
                  direction=direction, body=body, meta=meta)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def history(db: Session, customer_id: int, limit: int = 30):
    conv = db.query(Conversation).filter(Conversation.customer_id == customer_id).first()
    if not conv:
        return []
    return (db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.asc())
            .limit(limit).all())


def find_or_create_customer(db: Session, email: str = "", phone: str = "",
                            full_name: str = "") -> Customer:
    q = db.query(Customer)
    cust = None
    if email:
        cust = q.filter(Customer.email == email).first()
    if not cust and phone:
        cust = db.query(Customer).filter(Customer.phone == phone).first()
    if not cust:
        cust = Customer(full_name=full_name or email or phone or "Unknown",
                        email=email, phone=phone)
        db.add(cust)
        db.commit()
        db.refresh(cust)
    return cust
