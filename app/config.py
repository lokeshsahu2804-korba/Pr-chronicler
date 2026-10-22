"""Application configuration and environment variable management.

Uses Pydantic Settings and python-dotenv to load, validate, and access configuration
from environment variables and .env files.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always locate the project root containing .env regardless of current working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Explicitly populate os.environ from the project root .env if it exists
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)


class Settings(BaseSettings):
    """Application configuration settings."""

    # Server Configuration
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # Logging Configuration
    log_level: str = "INFO"
    log_file: str = "pr_chronicler.log"

    # GitHub Credentials & Testing (Phase 2 & 3)
    github_token: Optional[str] = None
    github_webhook_secret: Optional[str] = None
    github_test_repository: str = "encode/httpx"
    github_test_pr_number: int = 103

    # Google Generative AI / Gemini (Phase 4)
    gemini_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"

    @property
    def active_gemini_api_key(self) -> Optional[str]:
        """Return whichever Google/Gemini API key is configured."""
        candidates = [
            self.gemini_api_key,
            self.google_api_key,
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GOOGLE_API_KEY"),
        ]
        for key in candidates:
            if key and isinstance(key, str) and key.strip():
                return key.strip()
        return None

    # SMTP Dispatcher Configuration (Phase 5)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_email: Optional[str] = None
    smtp_app_password: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_from: Optional[str] = None
    dispatch_recipients: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_dry_run: bool = False

    @property
    def sender_email(self) -> Optional[str]:
        """Return configured sender email address."""
        return self.smtp_email or self.smtp_user or self.email_from

    @property
    def sender_password(self) -> Optional[str]:
        """Return configured sender app password."""
        return self.smtp_app_password or self.smtp_password

    @property
    def recipient_emails(self) -> list[str]:
        """Return list of recipient emails."""
        if self.dispatch_recipients and self.dispatch_recipients.strip():
            return [e.strip() for e in self.dispatch_recipients.split(",") if e.strip()]
        if self.sender_email:
            return [self.sender_email]
        return []

    model_config = SettingsConfigDict(
        env_file=(str(ENV_PATH), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()


settings = get_settings()
