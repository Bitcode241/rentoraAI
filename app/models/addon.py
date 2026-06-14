from sqlalchemy import String, Integer, Float, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AddOn(Base):
    """An optional extra a guest can add to a booking (GoPro, fuel, instructor,
    extra hour, transfer to beach...). Configured in admin. Applies to an asset
    type ('jetski','boat','transfer') or to all ('').

    Pricing:
      price        – the amount
      per_person   – if True, price is multiplied by the number of guests
    """
    __tablename__ = "add_ons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    per_person: Mapped[bool] = mapped_column(Boolean, default=False)
    # which asset type this add-on is offered for ("jetski","boat","transfer","")
    applies_to: Mapped[str] = mapped_column(String(32), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
