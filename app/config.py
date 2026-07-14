"""Application configuration, loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed application settings sourced from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    secret_key: str = "change-me-please-generate-a-long-random-value"
    database_url: str = "sqlite:///./data/app.db"
    upload_dir: str = "./data/uploads"
    backup_dir: str = "./data/backups"

    default_language: str = "de"
    secure_cookies: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    reminder_due_soon_days: int = 30
    max_upload_mb: int = 10

    # Brute-force protection: failed login/2FA attempts per client IP.
    rate_limit_max_attempts: int = 5
    rate_limit_window_seconds: int = 300

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "changeme"

    # --- Derived helpers ------------------------------------------------
    @property
    def upload_path(self) -> Path:
        p = (BASE_DIR / self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def backup_path(self) -> Path:
        p = (BASE_DIR / self.backup_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def supported_languages(self) -> tuple[str, ...]:
        return ("de", "en")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
