from sqlalchemy import String, Integer, DateTime, func, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(512), default="")
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=True, index=True)
    intent: Mapped[str] = mapped_column(String(32), default="")  # request|confirmation|cancellation|other
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    emails = relationship("EmailMessage", back_populates="thread", order_by="EmailMessage.created_at")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("email_threads.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    sender: Mapped[str] = mapped_column(String(255), default="")
    recipient: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(512), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(16), default="inbound")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("EmailThread", back_populates="emails")
