"""Plain, immutable inputs to the matching engine.

Building these from the database is the only impure step; everything else in
this package is a pure function of these values, which is what makes scores
reproducible for a given algorithm version.
"""

import json
from dataclasses import asdict, dataclass

from careeros.modules.sources.text import sha256

ALGORITHM_VERSION = "match-v1"


@dataclass(frozen=True)
class JobInput:
    title: str
    company: str
    location_text: str | None
    workplace_type: str | None
    employment_type: str | None
    description: str
    salary_min: int | None
    salary_max: int | None
    salary_interval: str | None
    status: str


@dataclass(frozen=True)
class LaneInput:
    name: str
    title_keywords: tuple[str, ...]
    title_exclude: tuple[str, ...]
    required_skills: tuple[str, ...]
    preferred_skills: tuple[str, ...]
    seniority_allowed: tuple[str, ...]
    employment_types: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    preferred_locations: tuple[str, ...]
    remote_ok: bool
    preferred_companies: tuple[str, ...]
    weights: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ProfileInput:
    """Only verified items. Work authorization reduced to yes/no/unknown flags."""

    verified_skills: tuple[str, ...] = ()
    unverified_skill_count: int = 0
    evidence_text: str = ""  # verified experience + project text, lowercase
    has_verified_evidence: bool = False
    current_location: str | None = None
    open_to_relocation: bool | None = None
    relocation_locations: tuple[str, ...] = ()
    salary_floor: int | None = None
    needs_sponsorship: str = "unknown"  # yes | no | unknown (unknown unless confirmed)


@dataclass(frozen=True)
class MatchInput:
    job: JobInput
    lane: LaneInput
    profile: ProfileInput

    def input_hash(self) -> str:
        payload = {
            "v": ALGORITHM_VERSION,
            "job": asdict(self.job),
            "lane": asdict(self.lane),
            "profile": asdict(self.profile),
        }
        return sha256(json.dumps(payload, sort_keys=True, default=str))
