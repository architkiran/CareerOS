"""User-assisted job intake. No network request is made to the submitted URL."""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Source
from careeros.modules.events.service import record_event
from careeros.modules.ingestion.service import upsert_job
from careeros.modules.sources.schemas import NormalizedJob
from careeros.modules.sources.text import canonicalize_url, html_to_text, sha256


class JobImport(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=2, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    description: str = Field(min_length=30, max_length=100_000)
    location: str = Field(default="", max_length=500)
    confirmed: bool = False

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        u = urlsplit(value)
        if u.scheme not in ("http", "https") or not u.hostname or u.username is not None:
            raise ValueError("Use an HTTP(S) job URL with no embedded credentials.")
        return value


def import_job(session: Session, data: JobImport) -> str:
    if not data.confirmed:
        raise ValueError(
            "Confirm that you supplied this posting text for your personal job search."
        )
    source = session.scalars(
        select(Source).where(
            Source.source_type == "manual",
            Source.board_token == "saved-jobs",  # noqa: S105 — local source identifier, not a credential
        )
    ).first()
    if source is None:
        source = Source(
            source_type="manual",
            board_token="saved-jobs",  # noqa: S106 — local identifier
            display_name="Added by you",
            enabled=False,
            config_json={"intake_only": True},
        )
        session.add(source)
        session.flush()
    normalized = NormalizedJob(
        external_id=sha256(canonicalize_url(data.url)),
        source_url=data.url,
        title=data.title,
        company_name=data.company,
        location_text=data.location or None,
        description_text=html_to_text(data.description),
        raw={
            "id": sha256(canonicalize_url(data.url)),
            "user_supplied": True,
            "url": data.url,
            "description": data.description,
        },
    )
    job, _ = upsert_job(session, source, normalized, utcnow())
    job.triage_status = "saved"
    record_event(
        session,
        "job.imported",
        "A user-provided opportunity was added for matching.",
        entity_type="job",
        entity_id=job.id,
    )
    return job.id
