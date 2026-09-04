from sqlalchemy import String, Integer, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Block(Base):
    """A period when a unit (or the whole fleet) cannot be booked.

    Covers the three real cases: bad weather, servicing, and the owner keeping a
    unit for personal use. A block with asset_id = NULL applies to every unit of
    that asset type — one entry closes the whole fleet for a stormy day.
    """
    __tablename__ = "blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(20), default="", index=True)
    start_datetime: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), index=True)
    end_datetime: Mapped["DateTime"] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(30), default="weather")
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
