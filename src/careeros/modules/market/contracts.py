from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostingEvidence(Strict):
    job_id: str
    title: str
    company: str
    source_url: str
    source_name: str
    first_seen_at: datetime
    last_seen_at: datetime
    source_date: datetime | None = None
    source_date_kind: str = "not_provided"
    matched_verified_skills: list[str]
    eligibility: str
    fit_score: int | None = Field(default=None, ge=0, le=100)

    @field_validator("source_url")
    @classmethod
    def public_link(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("Evidence links must be HTTP(S) URLs without credentials.")
        return value


class RoleFinding(Strict):
    key: str
    title: str
    explanation: str
    jobs: int = Field(ge=1)
    employers: int = Field(ge=1)
    verified_skills: list[str]
    additional_skills_to_review: list[str]
    evidence: list[PostingEvidence] = Field(max_length=5)
    observed_change: int | None = None


class MarketReport(Strict):
    algorithm_version: str = "market-v1"
    generated_at: datetime
    lookback_days: int = Field(ge=1, le=30)
    scope: str = "Configured public ATS feeds only"
    enabled_source_ids: list[str]
    fresh_source_ids: list[str]
    recent_active_jobs: int = Field(ge=0)
    verified_skill_count: int = Field(ge=0)
    findings: list[RoleFinding]
    warnings: list[str]
    baseline_brief_id: str | None = None
    baseline_at: datetime | None = None
    trend_note: str = "A comparable earlier daily snapshot is required; no trend is established."
