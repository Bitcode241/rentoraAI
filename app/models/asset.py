from sqlalchemy import String, Integer, Float, Boolean, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    asset_type: Mapped[str] = mapped_column(String(16), index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")
    price_hour: Mapped[float] = mapped_column(Float, default=0.0)
    price_half_day: Mapped[float] = mapped_column(Float, default=0.0)
    price_full_day: Mapped[float] = mapped_column(Float, default=0.0)
    deposit: Mapped[float] = mapped_column(Float, default=0.0)
    deposit_percent: Mapped[float] = mapped_column(Float, default=0.0)  # e.g. 30 = 30%
    requires_license: Mapped[bool] = mapped_column(Boolean, default=False)
    show_license_to_customer: Mapped[bool] = mapped_column(Boolean, default=True)
    fuel_policy: Mapped[str] = mapped_column(String(64), default="full-to-full")
    location: Mapped[str] = mapped_column(String(128), default="")
    calendar_id: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    packages = relationship("RentalPackage", back_populates="asset",
                            order_by="RentalPackage.duration_minutes",
                            cascade="all, delete-orphan")
