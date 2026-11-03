"""Application settings loaded from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from careeros.common.fs import private_dir

ModelProvider = Literal["disabled", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "sqlite:///./data/careeros.db"
    data_dir: Path = Path("./data")
    export_dir: Path = Path("./exports")
    log_level: str = "INFO"
    display_timezone: str = "America/New_York"

    scheduler_enabled: bool = False
    schedule_interval_hours: float = Field(default=24, ge=1, le=24 * 7)
    worker_enabled: bool = True  # run the task worker inside `careeros serve`
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    sse_heartbeat_seconds: float = Field(default=15.0, ge=1, le=120)

    # Runtime AI is disabled by default and spend caps default to $0 (ADR 0002).
    model_provider: ModelProvider = "disabled"
    model_daily_budget_usd: float = Field(default=0.0, ge=0)
    model_monthly_budget_usd: float = Field(default=0.0, ge=0)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    model_timeout_seconds: float = Field(default=60, ge=1, le=600)
    # Binding to a non-local address needs authentication that doesn't exist yet.
    allow_remote: bool = False
    # Set only by the provided Docker image: the app listens on 0.0.0.0 *inside* the container,
    # and docker-compose publishes the port to 127.0.0.1 on the host, so it stays local.
    container: bool = False
    backup_dir: Path = Path("./backups")

    @field_validator("database_url")
    @classmethod
    def _sqlite_only(cls, value: str) -> str:
        # ADR 0004: SQLite is the MVP database.
        if not value.startswith("sqlite"):
            raise ValueError("Only SQLite database URLs are supported in the MVP (ADR 0004).")
        return value

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value.upper() not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return value.upper()

    @property
    def is_localhost_bound(self) -> bool:
        if self.container and self.app_host in {"0.0.0.0", "::"}:  # noqa: S104
            return True  # reachable only through the host's 127.0.0.1 port mapping
        return self.app_host in {"127.0.0.1", "localhost", "::1"}

    def ensure_private_dirs(self) -> None:
        """Create data/export directories readable only by the current user.

        Tightening permissions is best-effort: a folder mounted into a container may belong
        to another user, which is fine as long as we can write to it.
        """
        for path in (self.data_dir, self.export_dir):
            private_dir(path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
