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
