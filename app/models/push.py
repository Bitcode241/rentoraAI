from sqlalchemy import String, Integer, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PushSubscription(Base):
    """One row per device that opted in to push notifications.

    The browser gives us an endpoint URL plus two keys; we store them so the
    server can wake that device when a booking comes in. A device can be removed
    at any time (or is pruned automatically when the push service says it's gone).
    """
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(255), default="")
    auth: Mapped[str] = mapped_column(String(255), default="")
    label: Mapped[str] = mapped_column(String(120), default="")  # e.g. "iPhone"
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
