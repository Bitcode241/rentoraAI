from sqlalchemy import String, Integer, DateTime, Boolean, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenancy import TenantMixin


class ApiKey(Base, TenantMixin):
    """A key that lets an external program act for one business.

    The raw key is shown once at creation and never stored — only its hash. If
    it's lost, you issue a new one. Scopes keep a read-only integration from
    being able to create bookings.
    """
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    prefix: Mapped[str] = mapped_column(String(16), default="", index=True)
    key_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    scopes: Mapped[str] = mapped_column(Text, default="read")  # comma separated
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), nullable=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
