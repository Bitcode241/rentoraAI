from sqlalchemy import String, Integer, Text, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tenancy import TenantMixin


class WaiverTemplate(Base, TenantMixin):
    """The terms a guest must accept, written by the owner — not by us.

    Separate text per asset type (a jet ski waiver is not a boat waiver) and per
    language. Editing bumps `version`; already-signed records keep their own copy
    of the text, so changing the template never rewrites history.
    """
    __tablename__ = "waiver_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(20), default="", index=True)
    lang: Mapped[str] = mapped_column(String(5), default="en", index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    require_document: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WaiverSignature(Base, TenantMixin):
    """A signed waiver — deliberately self-contained.

    We store the full text that was on screen at signing time, not a pointer to
    the template. If the owner later edits the terms, this record still shows
    exactly what the guest agreed to.
    """
    __tablename__ = "waiver_signatures"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(Integer, index=True)
    template_id: Mapped[int] = mapped_column(Integer, nullable=True)
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    asset_type: Mapped[str] = mapped_column(String(20), default="")
    lang: Mapped[str] = mapped_column(String(5), default="en")
    title_snapshot: Mapped[str] = mapped_column(String(200), default="")
    body_snapshot: Mapped[str] = mapped_column(Text, default="")
    signer_name: Mapped[str] = mapped_column(String(160), default="")
    signer_document: Mapped[str] = mapped_column(String(80), default="")
    signer_birth: Mapped[str] = mapped_column(String(20), default="")
    signature_png: Mapped[str] = mapped_column(Text, default="")  # base64 dataURL
    signed_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    signed_ip: Mapped[str] = mapped_column(String(60), default="")
    token: Mapped[str] = mapped_column(String(64), default="", index=True)
