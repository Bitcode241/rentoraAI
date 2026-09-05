from sqlalchemy import String, Integer, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    """One rental business on the platform.

    Every piece of operational data carries a tenant_id, and queries are filtered
    automatically (see app/core/tenancy.py) so one business can never see
    another's bookings — the filter is applied centrally rather than remembered
    in each query, because that is where such systems usually leak.
    """
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    slug: Mapped[str] = mapped_column(String(60), default="", index=True)
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_phone: Mapped[str] = mapped_column(String(60), default="")
    oib: Mapped[str] = mapped_column(String(20), default="")
    plan: Mapped[str] = mapped_column(String(30), default="standard")
    commission_percent: Mapped[float] = mapped_column(default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
