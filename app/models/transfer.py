from sqlalchemy import String, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class TransferZone(Base):
    """A transfer destination zone with one-way prices per vehicle type.

    Vehicle selection by passenger count:
      <= 3        -> 1 car
      4 .. 8      -> 1 van
      9 .. 11     -> 1 van + 1 car  (price = van + car)
      12 .. 16    -> 2 vans, etc. (handled by the splitter)
    Prices are ONE-WAY. Round trip = x2 (handled at quote time).
    """
    __tablename__ = "transfer_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)  # "Sheraton", "Zračna luka"
    car_price: Mapped[float] = mapped_column(Float, default=0.0)
    van_price: Mapped[float] = mapped_column(Float, default=0.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TransferRadius(Base):
    """GPS radius-based transfer pricing. A base point (e.g. Lapadska obala 4) and
    distance tiers: up to `max_km` from the base costs `car_price`/`van_price`
    one-way. The system geocodes the guest's location, measures distance to the
    base, and picks the smallest tier that fits. Beyond the largest tier -> ask
    the owner to set a price.
    """
    __tablename__ = "transfer_radii"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(128), default="")  # e.g. "do 10 km"
    base_label: Mapped[str] = mapped_column(String(255), default="")  # human base addr
    base_lat: Mapped[float] = mapped_column(Float, default=0.0)
    base_lng: Mapped[float] = mapped_column(Float, default=0.0)
    max_km: Mapped[float] = mapped_column(Float, default=10.0)
    car_price: Mapped[float] = mapped_column(Float, default=0.0)
    van_price: Mapped[float] = mapped_column(Float, default=0.0)
    # which brand/service this tier belongs to: "transfer" (Ragusa) etc.
    service: Mapped[str] = mapped_column(String(32), default="transfer")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
