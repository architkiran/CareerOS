"""Source registry and TOML watchlist loading."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.db.models import Source, SourceRun
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import get_or_create_company
from careeros.modules.sources.adapters.base import validate_token

SourceType = Literal["greenhouse", "lever", "ashby"]


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: SourceType
    token: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    rate_limit_seconds: float = Field(default=2.0, ge=0.5, le=60)

    def model_post_init(self, _context: object) -> None:
        validate_token(self.token)


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
