from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas import MessageCreate, MessageOut, AIChatRequest, AIChatResponse
from app.services import conversation_service
from app.integrations.gmail import gmail_service
from app.integrations.whatsapp import whatsapp_service
from app.models.customer import Customer
from app.ai.agent import run_agent

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/{customer_id}", response_model=List[MessageOut])
def get_history(customer_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return conversation_service.history(db, customer_id)


@router.post("/send", response_model=MessageOut)
def send_message(payload: MessageCreate, db: Session = Depends(get_db), _=Depends(get_current_user)):
    cust = db.get(Customer, payload.customer_id)
    if payload.channel == "email" and cust and cust.email:
        gmail_service.send(cust.email, "Message from rental team", payload.body)
    elif payload.channel == "whatsapp" and cust and cust.phone:
        whatsapp_service.send(cust.phone, payload.body)
    return conversation_service.add_message(
        db, payload.customer_id, payload.channel, "outbound", payload.body)


@router.post("/ai-reply", response_model=AIChatResponse)
def ai_reply(payload: AIChatRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    language = payload.language or "en"
    if payload.customer_id:
        cust = db.get(Customer, payload.customer_id)
        if cust:
            language = payload.language or cust.language
        conversation_service.add_message(
            db, payload.customer_id, payload.channel if payload.channel != "admin" else "email",
            "inbound", payload.message)
    result = run_agent(db, payload.message, language=language, customer_id=payload.customer_id)
    return AIChatResponse(**result)
