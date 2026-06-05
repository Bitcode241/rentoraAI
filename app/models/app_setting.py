from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AppSetting(Base):
    """Simple key-value store for admin-editable settings.

    This is the home for any tunable business rule that should live in the
    admin panel rather than .env — e.g. lead times, later: AI behaviour toggles,
    default deposit, etc. Values are stored as strings (JSON for structured ones).
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
