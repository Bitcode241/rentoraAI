from sqlalchemy.orm import Session
from app.models.audit import AuditLog


def record(db: Session, action: str, actor: str = "system", entity: str = "",
           entity_id: str = "", detail: str = ""):
    db.add(AuditLog(actor=actor, action=action, entity=entity,
                    entity_id=str(entity_id), detail=detail))
    db.commit()
