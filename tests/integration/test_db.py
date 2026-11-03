from pathlib import Path

import pytest
from sqlalchemy import text

from careeros.common.clock import utcnow
from careeros.config import Settings
from careeros.db.models import ActivityEvent
from careeros.db.session import create_sqlite_engine, make_session_factory


def test_connection_pragmas(settings: Settings) -> None:
    engine = create_sqlite_engine(settings.database_url)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 15000
    engine.dispose()


def test_creates_missing_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "x.db"
    engine = create_sqlite_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert db_path.exists()
    engine.dispose()


def test_rejects_non_sqlite_url() -> None:
    with pytest.raises(ValueError, match="SQLite"):
        create_sqlite_engine("postgresql://localhost/careeros")


def test_activity_event_roundtrip_keeps_utc(migrated_settings: Settings) -> None:
    engine = create_sqlite_engine(migrated_settings.database_url)
    factory = make_session_factory(engine)
    created = utcnow()
    with factory() as session:
        session.add(ActivityEvent(event_type="system.test", message="hello", created_at=created))
        session.commit()
    with factory() as session:
        event = session.query(ActivityEvent).one()
        assert event.created_at.tzinfo is not None
        assert abs((event.created_at - created).total_seconds()) < 1
        assert event.metadata_json == {}
    engine.dispose()
