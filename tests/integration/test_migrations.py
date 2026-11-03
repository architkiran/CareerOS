from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from careeros.config import Settings
from careeros.db.base import Base
from careeros.db.migrations import (
    alembic_config,
    current_revision,
    head_revision,
    upgrade_to_head,
)
from careeros.db.session import create_sqlite_engine


def test_upgrade_creates_tables_and_reaches_head(migrated_settings: Settings) -> None:
    engine = create_sqlite_engine(migrated_settings.database_url)
    tables = set(inspect(engine).get_table_names())
    assert {"activity_event", "setting", "alembic_version"} <= tables
    assert current_revision(engine) == head_revision(migrated_settings.database_url)
    engine.dispose()


def test_upgrade_is_idempotent(migrated_settings: Settings) -> None:
    upgrade_to_head(migrated_settings.database_url)  # second run must not fail
    engine = create_sqlite_engine(migrated_settings.database_url)
    assert current_revision(engine) == head_revision(migrated_settings.database_url)
    engine.dispose()


def test_downgrade_to_base_and_back(migrated_settings: Settings) -> None:
    cfg = alembic_config(migrated_settings.database_url)
    command.downgrade(cfg, "base")
    engine = create_sqlite_engine(migrated_settings.database_url)
    assert "activity_event" not in inspect(engine).get_table_names()
    assert current_revision(engine) is None
    command.upgrade(cfg, "head")
    assert "activity_event" in inspect(engine).get_table_names()
    engine.dispose()


def test_models_match_migrations(migrated_settings: Settings) -> None:
    """Fails if a model changes without a matching migration."""
    engine = create_sqlite_engine(migrated_settings.database_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
    engine.dispose()
