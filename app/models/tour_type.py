"""Tour catalog: one row per bookable tour (e.g. "Safari 90min"), with ONE stable
id that applies across every physical unit of that asset type.

Why this exists: physical units each carry their own price packages (needed for
availability), but for reporting and easy editing we want a single canonical tour.
A TourType is that canonical record. Editing it propagates to the per-unit packages;
reports group bookings by tour_type_id.
"""
from sqlalchemy import String, Integer, Float, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TourType(Base):
    __tablename__ = "tour_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)  # jetski/boat/transfer
    name: Mapped[str] = mapped_column(String(80))          # "Safari 90min (guided)"
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    deposit_percent: Mapped[float] = mapped_column(Float, default=0.0)  # 0 = use default
    guided: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
