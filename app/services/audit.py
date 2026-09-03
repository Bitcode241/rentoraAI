import json

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


def record(db: Session, action: str, actor: str = "system", entity: str = "",
           entity_id: str = "", detail: str = ""):
    """Append one entry to the audit trail. Never raises — logging must not break
    the operation it is recording."""
    try:
        db.add(AuditLog(actor=actor, action=action, entity=entity,
                        entity_id=str(entity_id), detail=detail))
        db.commit()
    except Exception:
        db.rollback()


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def record_change(db: Session, action: str, actor: str = "system",
                  entity: str = "", entity_id: str = "",
                  before: dict = None, after: dict = None, note: str = ""):
    """Record a change with a human-readable 'field: old -> new' summary.
    Only fields that actually changed are listed, so the log stays readable."""
    before = before or {}
    after = after or {}
    changes = []
    for k in after:
        old, new = before.get(k), after.get(k)
        if old != new:
            changes.append(f"{k}: {_fmt(old)} → {_fmt(new)}")
    text = note or "; ".join(changes) or "bez izmjena"
    payload = json.dumps({"before": {k: before.get(k) for k in after},
                          "after": after}, ensure_ascii=False, default=str)
    record(db, action, actor=actor, entity=entity, entity_id=entity_id,
           detail=f"{text}\n{payload}")


def snapshot(obj, fields) -> dict:
    """Grab the current values of `fields` from an ORM object."""
    return {f: getattr(obj, f, None) for f in fields}
