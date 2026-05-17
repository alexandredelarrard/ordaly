from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Configuration from environment variables and optional ``.env`` (cwd, e.g. ``/app/.env`` in Docker)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CRE Underwriting Inbound Pipeline"
    log_level: str = "INFO"
    # Directory for rotating log files (under Docker, mount host dir to this path — see compose)
    log_dir: Path = Field(default=Path(".log"))
    
    # Root for app data; ``incoming_documents`` is created under here. In Docker use /data + bind mount.
    data_root: Path = Field(default=Path("."))

    database_url: Optional[str] = None

    celery_broker_url: str = "redis://localhost:6379/0"

    jwt_secret_key: str = "dev-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 120

    secret_key_login: str = "dev-change-me-login"

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
