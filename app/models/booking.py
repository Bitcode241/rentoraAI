from sqlalchemy import String, Integer, Float, DateTime, func, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    start_datetime: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), index=True)
    end_datetime: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), index=True)
    total_price: Mapped[float] = mapped_column(Float, default=0.0)
    deposit_amount: Mapped[float] = mapped_column(Float, default=0.0)
    package_id: Mapped[int] = mapped_column(ForeignKey("rental_packages.id"), nullable=True)
    package_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    source: Mapped[str] = mapped_column(String(16), default="admin")
    notes: Mapped[str] = mapped_column(Text, default="")
    calendar_event_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asset = relationship("Asset")
    customer = relationship("Customer")
