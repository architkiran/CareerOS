"""System status checks shared by /health and the dashboard."""

from dataclasses import asdict, dataclass, field
from typing import Literal

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from careeros import __version__
from careeros.config import Settings
from careeros.db import migrations
from careeros.db.models import ActivityEvent

Status = Literal["ok", "degraded", "error"]


@dataclass
class DatabaseCheck:
    ok: bool
    journal_mode: str | None = None
    foreign_keys: bool | None = None
    error: str | None = None


@dataclass
class SchemaCheck:
    current_revision: str | None
    head_revision: str | None
    up_to_date: bool
    error: str | None = None


@dataclass
class SystemStatus:
    status: Status
    version: str
    environment: str
    localhost_only: bool
    database: DatabaseCheck
    schema: SchemaCheck
    scheduler_enabled: bool
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_database(engine: Engine) -> DatabaseCheck:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            fks = conn.execute(text("PRAGMA foreign_keys")).scalar()
        return DatabaseCheck(ok=True, journal_mode=str(journal), foreign_keys=bool(fks))
    except SQLAlchemyError as exc:
        return DatabaseCheck(ok=False, error=type(exc).__name__)


def check_schema(engine: Engine, database_url: str) -> SchemaCheck:
    try:
        head = migrations.head_revision(database_url)
        current = migrations.current_revision(engine)
    except SQLAlchemyError as exc:
        return SchemaCheck(None, None, False, error=type(exc).__name__)
    return SchemaCheck(current, head, up_to_date=current is not None and current == head)


def get_system_status(settings: Settings, engine: Engine) -> SystemStatus:
    db = check_database(engine)
    schema = (
        check_schema(engine, settings.database_url)
        if db.ok
        else SchemaCheck(None, None, False, error="database unavailable")
    )

    messages: list[str] = []
    status: Status = "ok"
    if not db.ok:
        status = "error"
        messages.append("Database is unreachable. Check DATABASE_URL and file permissions.")
    elif not schema.up_to_date:
        status = "degraded"
        messages.append("Database migrations are pending. Run: careeros migrate")
    if db.ok and db.journal_mode != "wal":
        messages.append(f"SQLite journal mode is {db.journal_mode!r}, expected 'wal'.")
    if not settings.is_localhost_bound:
        messages.append("Server is not bound to localhost. Add authentication before exposing it.")

    return SystemStatus(
        status=status,
        version=__version__,
        environment=settings.app_env,
        localhost_only=settings.is_localhost_bound,
        database=db,
        schema=schema,
        scheduler_enabled=settings.scheduler_enabled,
        messages=messages,
    )


def recent_events(session: Session, limit: int = 20) -> list[ActivityEvent]:
    stmt = select(ActivityEvent).order_by(ActivityEvent.id.desc()).limit(limit)
    return list(session.scalars(stmt))
