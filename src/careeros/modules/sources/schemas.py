from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

WorkplaceType = Literal["remote", "hybrid", "onsite"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship", "temporary"]


class NormalizedJob(BaseModel):
    """A job as stated by the source. Nothing here is inferred beyond explicit fields."""

    external_id: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=300)
    company_name: str = Field(min_length=1, max_length=200)
    location_text: str | None = Field(default=None, max_length=500)
    workplace_type: WorkplaceType | None = None
    employment_type: EmploymentType | None = None
    department: str | None = Field(default=None, max_length=200)
    description_text: str = ""
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, max_length=10)
    salary_interval: str | None = Field(default=None, max_length=20)
    posted_at: datetime | None = None
    raw: dict[str, Any]

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("source_url must be http(s)")
        return v

    @field_validator("posted_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
