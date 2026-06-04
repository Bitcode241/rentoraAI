from sqlalchemy import String, Integer, DateTime, ForeignKey, func, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ExternalRequest(Base):
    """A pending availability check sent to an external (partner) boat owner.

    Lifecycle:
      pending   -> owner has been asked, awaiting their reply
      confirmed -> owner said yes; booking created, guest notified
      declined  -> owner said no; guest notified
      timeout   -> owner didn't reply in time; escalated to the business owner
    """
    __tablename__ = "external_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    package_id: Mapped[int] = mapped_column(Integer, default=0)

    # what the guest asked for
    start_datetime: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))
    passengers: Mapped[int] = mapped_column(Integer, default=1)
    guest_email: Mapped[str] = mapped_column(String(255), default="")
    quoted_price: Mapped[float] = mapped_column(Integer, default=0)

    # which mailbox the guest used (so we reply to the guest from the same one)
    guest_mailbox: Mapped[str] = mapped_column(String(255), default="")

    # owner contact at time of request
    owner_email: Mapped[str] = mapped_column(String(255), default="")
    owner_phone: Mapped[str] = mapped_column(String(64), default="")

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # a short token the owner includes / we match in their reply
    token: Mapped[str] = mapped_column(String(12), index=True, default="")

    whatsapp_sent: Mapped[bool] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
