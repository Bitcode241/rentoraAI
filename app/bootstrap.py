"""Seed the default admin user on first run.

Fleet is NOT auto-seeded anymore — use scripts/seed_fleet.py to load the real
fleet, so the database reflects the actual business instead of demo data.
"""
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import hash_password
from app.core.logging import get_logger

log = get_logger("bootstrap")


def seed(db: Session):
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", email="admin@rental.local", role="admin",
                    hashed_password=hash_password("admin123")))
        db.commit()
        log.info("seeded_admin", username="admin")
