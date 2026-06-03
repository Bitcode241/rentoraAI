from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class RentalPackage(Base):
    """A bookable price package for an asset.

    Examples:
      Boat:   "4h" 240min 350.0 ; "8h" 480min 500.0 ; "Sunset 2h" 120min 250.0
      Jetski: "30 min" 30min 90.0 ; "1h" 60min 140.0 ; "Safari 90min" 90min 250.0
    """
    __tablename__ = "rental_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))            # "4h", "Sunset 2h", "Safari 90min"
    duration_minutes: Mapped[int] = mapped_column(Integer)   # used to compute end time / sort
    price: Mapped[float] = mapped_column(Float, default=0.0)
    guided: Mapped[bool] = mapped_column(Boolean, default=False)  # safari = with guide
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    asset = relationship("Asset", back_populates="packages")
