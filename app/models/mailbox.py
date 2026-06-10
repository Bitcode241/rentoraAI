from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Mailbox(Base):
    """An email address the AI watches and replies from.

    Managed via the admin panel (not .env) so non-technical owners can add their
    own addresses. All fields are editable through the UI.
    """
    __tablename__ = "mailboxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(255), unique=True)   # info@seagulldubrovnik.com
    username: Mapped[str] = mapped_column(String(255))               # usually same as address
    password: Mapped[str] = mapped_column(String(512))               # mailbox password
    imap_host: Mapped[str] = mapped_column(String(255))
    smtp_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    smtp_port: Mapped[int] = mapped_column(Integer, default=465)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Which kind of business this mailbox handles, for routing reminders/replies:
    # "" = any, "boat", "jetski", "transfer". e.g. seagull=boat, ragusa=transfer.
    handles_type: Mapped[str] = mapped_column(String(16), default="")
