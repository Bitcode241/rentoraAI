from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Rental Operating System"
    environment: str = "development"
    debug: bool = True

    database_url: str = "sqlite:///./data/rental.db"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    google_credentials_file: str = "credentials.json"
    google_token_file: str = "data/token.json"
    gmail_user: str = ""

    # Email via IMAP/SMTP (mailcow / custom domain / Gmail)
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_smtp_host: str = ""
    email_smtp_port: int = 465
    email_username: str = ""
    email_password: str = ""
    email_from: str = ""
    email_use_ssl: bool = True

    # Scheduler
    scheduler_enabled: bool = True
    email_poll_seconds: int = 120

    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = "verify-me"

    ai_confidence_threshold: float = 0.6
    ai_auto_send: bool = True
    default_language: str = "en"
    rate_limit: str = "100/minute"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
