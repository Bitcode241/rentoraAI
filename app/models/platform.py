from sqlalchemy import String, Integer, Text, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PlatformTerms(Base):
    """The platform's own terms — what a rental business accepts to use Rentora.

    Same versioning idea as guest waivers: editing the text bumps the version, and
    an acceptance stores its own copy, so you can always prove which wording a
    given customer agreed to and when.
    """
    __tablename__ = "platform_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    lang: Mapped[str] = mapped_column(String(5), default="hr", index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PlatformAcceptance(Base):
    """One record per user who accepted the platform terms."""
    __tablename__ = "platform_acceptances"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), default="", index=True)
    business_name: Mapped[str] = mapped_column(String(200), default="")
    terms_version: Mapped[int] = mapped_column(Integer, default=1)
    lang: Mapped[str] = mapped_column(String(5), default="hr")
    title_snapshot: Mapped[str] = mapped_column(String(200), default="")
    body_snapshot: Mapped[str] = mapped_column(Text, default="")
    accepted_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    accepted_ip: Mapped[str] = mapped_column(String(60), default="")
