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
    from app.ai.email_processor import detect_intent, RENTAL_INTENTS
    from app.core.logging import get_logger
    log = get_logger("whatsapp")
    data = await request.json()
    try:
        entry = data["entry"][0]["changes"][0]["value"]
        messages = entry.get("messages", [])
        # WhatsApp also sends "statuses" callbacks (delivery/read receipts) with
        # no 'messages' — ignore those, they are not guest inquiries.
        if not messages:
            return {"status": "ignored_no_message"}
        for m in messages:
            # only handle text messages; skip media/stickers/etc. for now
            if m.get("type") != "text":
                continue
            phone = m["from"]
            body = m.get("text", {}).get("body", "")
            # SAFETY FILTER: reply only to genuine rental inquiries (same as email)
            intent = detect_intent(body)
            if intent not in RENTAL_INTENTS:
                log.info("whatsapp_ignored_not_rental", phone=phone, intent=intent)
                # still record it so the owner can see it, but don't auto-reply
                customer = conversation_service.find_or_create_customer(db, phone=phone)
                conversation_service.add_message(db, customer.id, "whatsapp", "inbound", body)
                conv = conversation_service.get_or_create_conversation(db, customer.id)
                conv.needs_human = True
                db.commit()
                continue
            customer = conversation_service.find_or_create_customer(db, phone=phone)
            conversation_service.add_message(db, customer.id, "whatsapp", "inbound", body)
            result = run_agent(db, body, language=customer.language, customer_id=customer.id)
            if result["reply"] and not result["needs_human"] and settings.ai_auto_send:
                whatsapp_service.send(phone, result["reply"])
                conversation_service.add_message(db, customer.id, "whatsapp", "outbound", result["reply"])
            else:
                conv = conversation_service.get_or_create_conversation(db, customer.id)
                conv.needs_human = True
                db.commit()
    except (KeyError, IndexError):
        pass
    return {"status": "received"}
