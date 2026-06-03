from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.services import conversation_service
from app.integrations.whatsapp import whatsapp_service
from app.ai.agent import run_agent

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
def verify(mode: str = Query(None, alias="hub.mode"),
           token: str = Query(None, alias="hub.verify_token"),
           challenge: str = Query(None, alias="hub.challenge")):
    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        return PlainTextResponse(challenge or "")
    raise HTTPException(403, "Verification failed")


@router.post("/whatsapp")
async def incoming(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        for m in messages:
            phone = m["from"]
            body = m.get("text", {}).get("body", "")
            customer = conversation_service.find_or_create_customer(db, phone=phone)
            conversation_service.add_message(db, customer.id, "whatsapp", "inbound", body)
            result = run_agent(db, body, language=customer.language, customer_id=customer.id)
            if result["reply"] and not result["needs_human"]:
                whatsapp_service.send(phone, result["reply"])
                conversation_service.add_message(db, customer.id, "whatsapp", "outbound", result["reply"])
    except (KeyError, IndexError):
        pass
    return {"status": "received"}
