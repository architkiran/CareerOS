"""SQLite engine and session factory.

Every connection enables WAL mode, foreign keys, and a busy timeout.
"""

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

BUSY_TIMEOUT_MS = 15000


def _apply_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_sqlite_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Only SQLite is supported in the MVP (ADR 0004).")
    if url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


@lru_cache
def get_engine(database_url: str) -> Engine:
    return create_sqlite_engine(database_url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        yield session
