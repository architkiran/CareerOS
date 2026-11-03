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


def test_0006_repairs_collapsed_jobs(settings: Settings) -> None:
    from sqlalchemy import text

    settings.ensure_private_dirs()
    cfg = alembic_config(settings.database_url)
    command.upgrade(cfg, "0005")
    engine = create_sqlite_engine(settings.database_url)
    now = "2026-11-03 10:00:00"
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO company (id, canonical_name, normalized_name) VALUES ('c','S','s')")
        )
        c.execute(
            text(
                "INSERT INTO source (id, source_type, board_token, display_name, enabled, "
                "rate_limit_seconds, config_json, consecutive_failures, created_at) VALUES "
                "('s','greenhouse','stripe','Stripe',1,2,'{}',0,:n)"
            ),
            {"n": now},
        )
        c.execute(
            text(
                "INSERT INTO job (id, canonical_url, company_id, title, normalized_title, "
                "description_text, description_hash, dedupe_key, first_seen_at, "
                "last_seen_at, status, triage_status) VALUES ('j','https://stripe.com/jobs/search',"
                "'c','Role 0','role 0','','h','k',:n,:n,'active','shortlisted')"
            ),
            {"n": now},
        )
        for i in range(3):
            c.execute(
                text(
                    "INSERT INTO job_source_record (id, job_id, source_id, external_id, "
                    "source_url, raw_json, raw_hash, first_seen_at, last_seen_at) VALUES "
                    "(:id,'j','s',:ext,:url,'{}','h',:t,:t)"
                ),
                {
                    "id": f"r{i}",
                    "ext": str(i),
                    "t": f"2026-11-03 10:00:0{i}",
                    "url": f"https://stripe.com/jobs/search?gh_jid={i}",
                },
            )
    command.upgrade(cfg, "0006")
    with engine.connect() as c:
        assert c.execute(text("SELECT id FROM job_source_record")).scalars().all() == ["r0"]
        job = c.execute(text("SELECT canonical_url, triage_status FROM job")).one()
        assert job == ("https://stripe.com/jobs/search?gh_jid=0", "shortlisted")
        msg = c.execute(
            text("SELECT message FROM activity_event WHERE event_type='system.repair'")
        ).scalar_one()
        assert "Repaired 2" in msg
    command.upgrade(cfg, "0006")  # idempotent at head
    engine.dispose()


def test_0006_noop_on_clean_data(migrated_settings: Settings) -> None:
    from sqlalchemy import text

    engine = create_sqlite_engine(migrated_settings.database_url)
    with engine.connect() as c:
        assert (
            c.execute(
                text("SELECT count(*) FROM activity_event WHERE event_type='system.repair'")
            ).scalar_one()
            == 0
        )
    engine.dispose()


def test_migrations_dir_resolution(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest as _pytest

    from careeros.db import migrations as m

    real = m.migrations_dir()
    assert (real / "env.py").is_file()
    monkeypatch.setenv("CAREEROS_MIGRATIONS_DIR", str(real))
    assert m.migrations_dir() == real
    # Installed (non-editable) layout: source checkout path absent, fall back to ./migrations.
    monkeypatch.delenv("CAREEROS_MIGRATIONS_DIR")
    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path / "site-packages")
    monkeypatch.chdir(real.parent)
    assert m.migrations_dir() == real.parent / "migrations"
    monkeypatch.chdir(tmp_path)
    with _pytest.raises(FileNotFoundError, match="CAREEROS_MIGRATIONS_DIR"):
        m.migrations_dir()
