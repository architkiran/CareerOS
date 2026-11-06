"""Plain, immutable inputs to the matching engine.

Building these from the database is the only impure step; everything else in
this package is a pure function of these values, which is what makes scores
reproducible for a given algorithm version.
"""

import json
from dataclasses import asdict, dataclass
from functools import lru_cache

from careeros.modules.sources.text import sha256

ALGORITHM_VERSION = "match-v3"  # v3: stale employer evidence cannot establish current policy


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
    employer_policy: str = "unknown"  # from accepted official evidence (Phase 5)
    employer_policy_note: str | None = None


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
        # Each part is hashed once and cached: a rescore compares thousands of job/lane pairs.
        parts = (ALGORITHM_VERSION, _digest(self.job), _digest(self.lane), _digest(self.profile))
        return sha256("|".join(parts))


@lru_cache(maxsize=16_384)
def _digest(part: JobInput | LaneInput | ProfileInput) -> str:
    return sha256(json.dumps(asdict(part), sort_keys=True, default=str))
