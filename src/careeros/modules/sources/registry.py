"""Source registry and TOML watchlist loading."""

import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Source, SourceRun
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import get_or_create_company
from careeros.modules.sources.adapters.base import validate_token

SourceType = Literal["greenhouse", "lever", "ashby", "smartrecruiters", "remotive", "jobicy"]


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate_limit_seconds: float = Field(default=2.0, ge=0.5, le=60)
    refresh_interval_minutes: int | None = Field(default=None, ge=15, le=10_080)


class SourceIn(SourcePolicy):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    token: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    rate_limit_seconds: float = Field(default=2.0, ge=0.5, le=60)

    def model_post_init(self, _context: object) -> None:
        validate_token(self.token)
        fixed = {"remotive": "public", "jobicy": "usa"}
        if self.type in fixed and self.token != fixed[self.type]:
            raise ValueError("This public board uses a fixed identifier: " + fixed[self.type])


class DuplicateSourceError(ValueError):
    pass


def find_source(session: Session, source_type: str, token: str) -> Source | None:
    stmt = select(Source).where(Source.source_type == source_type, Source.board_token == token)
    return session.scalars(stmt).first()


def add_source(session: Session, data: SourceIn) -> Source:
    if find_source(session, data.type, data.token):
        raise DuplicateSourceError(f"{data.type}/{data.token} is already configured.")
    company = get_or_create_company(session, data.name)
    source = Source(
        source_type=data.type,
        board_token=data.token,
        display_name=data.name,
        company_id=company.id,
        enabled=data.enabled,
        rate_limit_seconds=data.rate_limit_seconds,
        config_json=(
            {"refresh_interval_minutes": data.refresh_interval_minutes}
            if data.refresh_interval_minutes is not None
            else {}
        ),
    )
    session.add(source)
    session.flush()
    record_event(
        session,
        "source.added",
        f"Source added: {data.name} ({data.type})",
        entity_type="source",
        entity_id=source.id,
    )
    return source


def set_source_enabled(session: Session, source_id: str, enabled: bool) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise LookupError("Source not found")
    source.enabled = enabled
    if enabled:
        source.consecutive_failures = 0
    record_event(
        session,
        "source.updated",
        f"Source {'enabled' if enabled else 'disabled'}: {source.display_name}",
        entity_type="source",
        entity_id=source.id,
    )
    return source


def list_sources(session: Session) -> list[Source]:
    return list(session.scalars(select(Source).order_by(Source.display_name)))


def last_run(session: Session, source_id: str) -> SourceRun | None:
    stmt = (
        select(SourceRun)
        .where(SourceRun.source_id == source_id)
        .order_by(SourceRun.started_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


@dataclass
class SyncResult:
    added: int
    existing: int
    disabled: int = 0


def load_watchlist(path: Path) -> list[SourceIn]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    entries = data.get("source", [])
    if not isinstance(entries, list):
        raise ValueError("Expected [[source]] tables in the watchlist file.")
    return [SourceIn.model_validate(e) for e in entries]


def sync_watchlist(session: Session, entries: list[SourceIn]) -> SyncResult:
    """Add missing sources, and disable existing ones the file marks `enabled = false`.

    Never re-enables a source and never changes anything else, so choices made in the
    dashboard are kept. Safe to run on every start.
    """
    added = existing = disabled = 0
    for entry in entries:
        source = find_source(session, entry.type, entry.token)
        if source is None:
            add_source(session, entry)
            added += 1
            continue
        existing += 1
        if not entry.enabled and source.enabled:
            set_source_enabled(session, source.id, False)
            disabled += 1
    return SyncResult(added, existing, disabled)


def source_policy(source: Source) -> SourcePolicy:
    value = (source.config_json or {}).get("refresh_interval_minutes")
    if isinstance(value, bool) or not isinstance(value, int) or not 15 <= value <= 10_080:
        value = None
    return SourcePolicy(
        rate_limit_seconds=source.rate_limit_seconds, refresh_interval_minutes=value
    )


def set_source_policy(session: Session, source_id: str, policy: SourcePolicy) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise LookupError("Source not found")
    source.rate_limit_seconds = policy.rate_limit_seconds
    config = dict(source.config_json or {})
    if policy.refresh_interval_minutes is None:
        config.pop("refresh_interval_minutes", None)
    else:
        config["refresh_interval_minutes"] = policy.refresh_interval_minutes
    source.config_json = config
    record_event(
        session,
        "source.policy_updated",
        "Source refresh policy updated.",
        entity_type="source",
        entity_id=source.id,
    )
    return source


def due_source_ids(session: Session, now: datetime | None = None) -> list[str]:
    """Optional per-source minimum gaps apply to scheduled missions, not explicit manual runs."""
    now = now or utcnow()
    last_attempt = (
        select(SourceRun.source_id, func.max(SourceRun.started_at).label("checked_at"))
        .group_by(SourceRun.source_id)
        .subquery()
    )
    rows = session.execute(
        select(Source, last_attempt.c.checked_at)
        .outerjoin(last_attempt, last_attempt.c.source_id == Source.id)
        .where(Source.enabled.is_(True))
    )
    due = []
    for source, checked_at in rows:
        minutes = source_policy(source).refresh_interval_minutes
        reference = checked_at or source.last_success_at
        if minutes is None or reference is None or now - reference >= timedelta(minutes=minutes):
            due.append(source.id)
    return due
