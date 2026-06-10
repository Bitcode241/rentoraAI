from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.mailbox import Mailbox

router = APIRouter(prefix="/api/mailboxes", tags=["mailboxes"])


class MailboxIn(BaseModel):
    address: str
    username: Optional[str] = None     # defaults to address if omitted
    password: Optional[str] = None     # only set/changed when provided
    imap_host: str
    smtp_host: str
    imap_port: int = 993
    smtp_port: int = 465
    use_ssl: bool = True
    active: bool = True
    handles_type: str = ""


class MailboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    address: str
    username: str
    imap_host: str
    smtp_host: str
    imap_port: int
    smtp_port: int
    use_ssl: bool
    active: bool
    handles_type: str = ""
    has_password: bool = False         # never expose the actual password


def _to_out(m: Mailbox) -> dict:
    return {
        "id": m.id, "address": m.address, "username": m.username,
        "imap_host": m.imap_host, "smtp_host": m.smtp_host,
        "imap_port": m.imap_port, "smtp_port": m.smtp_port,
        "use_ssl": m.use_ssl, "active": m.active,
        "handles_type": getattr(m, "handles_type", "") or "",
        "has_password": bool(m.password),
    }


@router.get("", response_model=List[MailboxOut])
def list_mailboxes(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [_to_out(m) for m in db.query(Mailbox).order_by(Mailbox.address).all()]


@router.post("", response_model=MailboxOut, dependencies=[Depends(require_admin)])
def create_mailbox(payload: MailboxIn, db: Session = Depends(get_db)):
    if db.query(Mailbox).filter(Mailbox.address == payload.address).first():
        raise HTTPException(409, "Mailbox with that address already exists")
    m = Mailbox(
        address=payload.address,
        username=payload.username or payload.address,
        password=payload.password or "",
        imap_host=payload.imap_host, smtp_host=payload.smtp_host,
        imap_port=payload.imap_port, smtp_port=payload.smtp_port,
        use_ssl=payload.use_ssl, active=payload.active,
        handles_type=payload.handles_type or "",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.patch("/{mailbox_id}", response_model=MailboxOut,
              dependencies=[Depends(require_admin)])
def update_mailbox(mailbox_id: int, payload: MailboxIn, db: Session = Depends(get_db)):
    m = db.get(Mailbox, mailbox_id)
    if not m:
        raise HTTPException(404, "Mailbox not found")
    m.address = payload.address
    m.username = payload.username or payload.address
    # only overwrite password if a new one was provided (blank = keep existing)
    if payload.password:
        m.password = payload.password
    m.imap_host = payload.imap_host
    m.smtp_host = payload.smtp_host
    m.imap_port = payload.imap_port
    m.smtp_port = payload.smtp_port
    m.use_ssl = payload.use_ssl
    m.active = payload.active
    m.handles_type = payload.handles_type or ""
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.delete("/{mailbox_id}", dependencies=[Depends(require_admin)])
def delete_mailbox(mailbox_id: int, db: Session = Depends(get_db)):
    m = db.get(Mailbox, mailbox_id)
    if not m:
        raise HTTPException(404, "Mailbox not found")
    db.delete(m)
    db.commit()
    return {"deleted": mailbox_id}


@router.post("/{mailbox_id}/test", dependencies=[Depends(require_admin)])
def test_mailbox(mailbox_id: int, db: Session = Depends(get_db)):
    """Try to connect (IMAP login) so the owner sees if credentials work."""
    import imaplib
    m = db.get(Mailbox, mailbox_id)
    if not m:
        raise HTTPException(404, "Mailbox not found")
    try:
        conn = imaplib.IMAP4_SSL(m.imap_host, m.imap_port)
        conn.login(m.username, m.password)
        conn.select("INBOX")
        conn.logout()
        return {"ok": True, "message": "Connection successful"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
