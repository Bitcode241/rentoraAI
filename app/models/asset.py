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
    page_url: Mapped[str] = mapped_column(String(512), default="")  # public boat page
    default_pickup: Mapped[str] = mapped_column(String(255), default="")  # partner's usual pickup
    calendar_id: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # External (partner) assets: not owned by the business. The AI must ask the
    # owner for availability before confirming. Only the super-admin manages these.
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_name: Mapped[str] = mapped_column(String(128), default="")
    owner_email: Mapped[str] = mapped_column(String(255), default="")
    owner_phone: Mapped[str] = mapped_column(String(64), default="")  # WhatsApp later
    commission_percent: Mapped[float] = mapped_column(Float, default=0.0)  # your cut, e.g. 15
    # Who collects the guest's money for this partner asset:
    #  "you"     = you charge the guest, you owe the owner (price - your cut)
    #  "partner" = the partner charges the guest, they owe you your cut
    payment_direction: Mapped[str] = mapped_column(String(16), default="you")
    # Availability chain: when several boats are the same model, the one with the
    # LOWEST priority is offered first (your own boat = 1, then partners you choose).
    booking_priority: Mapped[int] = mapped_column(Integer, default=100)
    # Group equivalent boats so the chain knows they're interchangeable
    # (e.g. all "Barracuda 545" share model_group="barracuda-545").
    model_group: Mapped[str] = mapped_column(String(64), default="")
    # --- Booking-widget provider model (super-admin only) ---
    # "own"     = your own boat/tour; guest pays you (deposit or full) online.
    # "partner" = a partner runs the tour; ONLY your commission is charged online,
    #             the rest is paid directly to the partner on the boat.
    provider_type: Mapped[str] = mapped_column(String(16), default="own")
    provider_name: Mapped[str] = mapped_column(String(160), default="")  # obrt naziv
    provider_oib: Mapped[str] = mapped_column(String(32), default="")    # OIB izvođača
    partner_total_price: Mapped[float] = mapped_column(Float, default=0.0)  # ukupna cijena
    my_commission: Mapped[float] = mapped_column(Float, default=0.0)        # online dio
    # Boost level (future): partners who accept a higher commission get ranked
    # higher and pushed harder (Google Ads etc). 0 = none. Stored now so the
    # ranking/billing engine can be built on top without another migration.
    boost_level: Mapped[int] = mapped_column(Integer, default=0)
    # Temporary operational stop (breakdown, service, partner pulled it). The boat
    # stays in the system but is skipped by availability + the chain moves to the
    # next boat. Different from `active` (which removes it entirely).
    out_of_service: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    packages = relationship("RentalPackage", back_populates="asset",
                            order_by="RentalPackage.duration_minutes",
                            cascade="all, delete-orphan")
