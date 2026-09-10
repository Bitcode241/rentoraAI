from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.roles import ROLE_LABELS, role_of, require
from app.core.security import get_current_user, hash_password
from app.core.tenancy import get_tenant, DEFAULT_TENANT_ID, all_tenants
from app.models.user import User

router = APIRouter(prefix="/api/staff", tags=["staff"])
require_staff = require("staff")


def _out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "email": u.email or "",
            "role": role_of(u), "role_label": ROLE_LABELS.get(role_of(u), ""),
            "active": bool(u.active)}


@router.get("")
def list_staff(db: Session = Depends(get_db), _=Depends(require_staff)):
    rows = db.query(User).order_by(User.username).all()
    return {"roles": ROLE_LABELS, "staff": [_out(u) for u in rows]}


@router.post("")
def create_staff(payload: dict, db: Session = Depends(get_db),
                 _=Depends(require_staff)):
    """Add a team member. Usernames are unique across the platform, so we check
    globally even though the account belongs to this business."""
    from app.services import audit
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or "skipper").strip()
    if not username or len(username) < 3:
        raise HTTPException(400, "Korisničko ime mora imati barem 3 znaka.")
    if len(password) < 8:
        raise HTTPException(400, "Lozinka mora imati barem 8 znakova.")
    if role not in ROLE_LABELS:
        raise HTTPException(400, "Nepoznata uloga.")
    if role == "owner" and role_of(_) != "owner":
        raise HTTPException(403, "Samo vlasnik može dodati drugog vlasnika.")
    with all_tenants():
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(400, "Korisničko ime je zauzeto.")
    u = User(username=username, email=(payload.get("email") or "").strip(),
             hashed_password=hash_password(password), role=role, active=True,
             tenant_id=get_tenant() or DEFAULT_TENANT_ID)
    db.add(u)
    db.commit()
    db.refresh(u)
    audit.record(db, "staff_created", actor=getattr(_, "username", "admin"),
                 entity="user", entity_id=u.id,
                 detail=f"{username} — {ROLE_LABELS.get(role, role)}")
    return {"ok": True, "user": _out(u)}


@router.put("/{user_id}")
def update_staff(user_id: int, payload: dict, db: Session = Depends(get_db),
                 _=Depends(require_staff)):
    from app.services import audit
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Korisnik nije pronađen.")
    before = role_of(u)
    if "role" in payload:
        role = str(payload["role"]).strip()
        if role not in ROLE_LABELS:
            raise HTTPException(400, "Nepoznata uloga.")
        if (role == "owner" or before == "owner") and role_of(_) != "owner":
            raise HTTPException(403, "Samo vlasnik može mijenjati vlasnika.")
        u.role = role
    if "active" in payload:
        if u.id == getattr(_, "id", None) and not payload["active"]:
            raise HTTPException(400, "Ne možeš deaktivirati sam sebe.")
        u.active = bool(payload["active"])
    if payload.get("password"):
        if len(payload["password"]) < 8:
            raise HTTPException(400, "Lozinka mora imati barem 8 znakova.")
        u.hashed_password = hash_password(payload["password"])
    db.commit()
    audit.record(db, "staff_updated", actor=getattr(_, "username", "admin"),
                 entity="user", entity_id=u.id,
                 detail=f"{u.username}: {before} → {role_of(u)}"
                        f"{' (lozinka promijenjena)' if payload.get('password') else ''}")
    return {"ok": True, "user": _out(u)}


@router.get("/me")
def me(user=Depends(get_current_user)):
    """What the logged-in user is allowed to see — the UI uses this to hide
    sections it must not show."""
    from app.core.roles import PERMISSIONS
    r = role_of(user)
    return {"username": user.username, "role": r,
            "role_label": ROLE_LABELS.get(r, ""),
            "permissions": sorted(PERMISSIONS.get(r, set()))}
