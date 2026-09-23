from sqlalchemy import String, Integer, Float, Text, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenancy import TenantMixin


class Partner(Base, TenantMixin):
    """Someone you trade tours with — you send them guests, they send you guests,
    and the balance is settled periodically rather than per booking."""
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    contact: Mapped[str] = mapped_column(String(160), default="")
    phone: Mapped[str] = mapped_column(String(60), default="")
    oib: Mapped[str] = mapped_column(String(20), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class PartnerEntry(Base, TenantMixin):
    """One line on a partner's running account.

    Sign convention, from the owner's point of view:
        amount > 0  → the partner owes me
        amount < 0  → I owe the partner

    The balance is just the sum. That keeps offsetting ("prebijanje") natural:
    an old debt and a new earning simply add up.
    """
    __tablename__ = "partner_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(24), default="referral")
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    # context, so a line can be explained months later
    tour_name: Mapped[str] = mapped_column(String(160), default="")
    guests: Mapped[int] = mapped_column(Integer, default=0)
    guest_paid: Mapped[float] = mapped_column(Float, default=0.0)
    partner_gets: Mapped[float] = mapped_column(Float, default=0.0)
    booking_id: Mapped[int] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    entry_date: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    created_by: Mapped[str] = mapped_column(String(120), default="")
