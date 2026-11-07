"""Validated input/output shapes for the profile module."""

import re
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

VerifiedStatus = Literal["verified", "unverified"]
YesNoUnknown = Literal["yes", "no", "unknown"]
Seniority = Literal["entry", "junior", "mid", "senior", "lead"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship", "temporary"]
Proficiency = Literal["beginner", "intermediate", "advanced", "expert"]
FactCategory = Literal[
    "education",
    "employment",
    "achievement",
    "leadership",
    "certification",
    "contact",
    "preference",
    "other",
]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]
Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


class ProfileIn(_Strict):
    display_name: ShortText = ""
    email: ShortText | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    current_location: ShortText | None = None
    open_to_relocation: bool | None = None
    relocation_locations: list[Term] = Field(default_factory=list, max_length=50)
    graduation_date: date | None = None
    availability_date: date | None = None
    salary_floor: int | None = Field(default=None, ge=0, le=10_000_000)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not _EMAIL.match(v):
            raise ValueError("Enter a valid email address.")
        return v or None

    @field_validator("relocation_locations")
    @classmethod
    def _locs(cls, v: list[str]) -> list[str]:
        return _dedupe(v)


class FactIn(_Strict):
    category: FactCategory
    fact_key: Name
    fact_value: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
    ]
    source_note: LongText | None = None
    verified_status: VerifiedStatus = "unverified"


class SkillIn(_Strict):
    name: Term
    proficiency: Proficiency | None = None
    last_used_year: int | None = Field(default=None, ge=1950, le=2100)
    verified_status: VerifiedStatus = "unverified"


class ExperienceIn(_Strict):
    organization: Name
    title: Name
    start_date: date | None = None
    end_date: date | None = None
    description: LongText | None = None
    verified_status: VerifiedStatus = "unverified"

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date cannot be before start date.")
        return self


class ProjectIn(_Strict):
    name: Name
    description: LongText | None = None
    technologies: list[Term] = Field(default_factory=list, max_length=50)
    outcomes: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    ] = Field(default_factory=list, max_length=20)
    evidence_notes: LongText | None = None
    verified_status: VerifiedStatus = "unverified"


def _default_seniority() -> list[Seniority]:
    return ["entry", "junior", "mid"]


def _default_employment() -> list[EmploymentType]:
    return ["full_time"]


class LaneRules(_Strict):
    title_keywords: list[Term] = Field(default_factory=list)
    title_exclude: list[Term] = Field(default_factory=list)
    required_skills: list[Term] = Field(default_factory=list)
    preferred_skills: list[Term] = Field(default_factory=list)
    seniority_allowed: list[Seniority] = Field(default_factory=_default_seniority)
    employment_types: list[EmploymentType] = Field(default_factory=_default_employment)
    excluded_terms: list[Term] = Field(default_factory=list)
    preferred_locations: list[Term] = Field(default_factory=list)
    remote_ok: bool = True
    preferred_companies: list[Term] = Field(default_factory=list)


class LaneWeights(_Strict):
    role_title: int = Field(default=20, ge=0, le=100)
    skills: int = Field(default=25, ge=0, le=100)
    experience: int = Field(default=20, ge=0, le=100)
    seniority: int = Field(default=10, ge=0, le=100)
    location: int = Field(default=10, ge=0, le=100)
    compensation: int = Field(default=5, ge=0, le=100)
    preference: int = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def _sum(self) -> Self:
        total = sum(self.model_dump().values())
        if total != 100:
            raise ValueError(f"Scoring weights must add up to 100 (currently {total}).")
        return self


class LaneIn(_Strict):
    name: Term
    enabled: bool = True
    rules: LaneRules = Field(default_factory=LaneRules)
    weights: LaneWeights = Field(default_factory=LaneWeights)


class WorkAuthorizationIn(_Strict):
    status_text: ShortText | None = None
    requires_sponsorship_now: YesNoUnknown = "unknown"
    requires_sponsorship_future: YesNoUnknown = "unknown"
    authorized_until: date | None = None
    constraints: LongText | None = None
    notes: LongText | None = None
    confirmed: bool = False


class ProfileExport(_Strict):
    schema_version: Literal[1] = 1
    exported_at: datetime | None = None
    profile: ProfileIn
    facts: list[FactIn] = Field(default_factory=list)
    skills: list[SkillIn] = Field(default_factory=list)
    experiences: list[ExperienceIn] = Field(default_factory=list)
    projects: list[ProjectIn] = Field(default_factory=list)
    lanes: list[LaneIn] = Field(default_factory=list)
    work_authorization: WorkAuthorizationIn | None = None
