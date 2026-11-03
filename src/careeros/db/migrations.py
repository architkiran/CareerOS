"""Alembic helpers used by the CLI and health checks.

Migrations are applied only by an explicit command, never at app startup.
"""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def migrations_dir() -> Path:
    """Where the Alembic scripts live.

    CAREEROS_MIGRATIONS_DIR wins (set by the Docker image); then the source checkout
    (editable installs); then ./migrations relative to the working directory.
    """
    override = os.environ.get("CAREEROS_MIGRATIONS_DIR")
    candidates = [Path(override)] if override else []
    candidates += [PROJECT_ROOT / "migrations", Path.cwd() / "migrations"]
    for path in candidates:
        if (path / "env.py").is_file():
            return path
    raise FileNotFoundError(
        "Can't find the migrations folder. Set CAREEROS_MIGRATIONS_DIR to its path."
    )


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def head_revision(database_url: str) -> str | None:
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
