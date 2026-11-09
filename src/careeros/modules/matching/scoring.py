"""Explainable weighted score (0-100) per job and lane.

A dimension with no information (e.g. salary not disclosed) counts as neutral
(half its weight): never zero, never full marks. `completeness` reports how
much of the weight was backed by real information, so a thin posting can't
outrank a well-described one on guesses.
"""

from dataclasses import dataclass, field
from typing import Any

from careeros.modules.matching.filters import (
    FilterResult,
    combine,
    employment_filter,
    excluded_terms_filter,
    location_filter,
    seniority_filter,
    status_filter,
    title_exclude_filter,
    work_authorization_filter,
)
from careeros.modules.matching.inputs import ALGORITHM_VERSION, MatchInput
from careeros.modules.matching.seniority import infer_seniority
from careeros.modules.matching.text import SENIORITY_ORDER, contains_term, title_key

NEUTRAL = 0.5

DIMENSION_LABELS = {
    "role_title": "Role / title alignment",
    "skills": "Skills alignment",
    "experience": "Experience / project evidence",
    "seniority": "Seniority fit",
    "location": "Location / work arrangement",
    "compensation": "Compensation",
    "preference": "Employer / role preference",
}


@dataclass
class Dimension:
    key: str
    weight: int
    score: float | None  # 0..1, None = no information
    explanation: str

    @property
    def effective(self) -> float:
        return NEUTRAL if self.score is None else self.score

    @property
    def points(self) -> float:
        return round(self.effective * self.weight, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": DIMENSION_LABELS[self.key],
            "weight": self.weight,
            "score": None if self.score is None else round(self.score, 3),
            "points": self.points,
            "neutral": self.score is None,
            "explanation": self.explanation,
        }


@dataclass
class MatchResult:
    classified: bool
    eligibility: str
    score: int
    completeness: int
    dimensions: list[Dimension]
    filters: list[FilterResult]
    matched_skills: list[str]
    missing_skills: list[str]
    risks: list[str]
    seniority: dict[str, Any]
    explanation: str
    input_hash: str
    algorithm_version: str = ALGORITHM_VERSION
    notes: list[str] = field(default_factory=list)

    def breakdown(self) -> dict[str, Any]:
        return {
            "dimensions": [d.to_dict() for d in self.dimensions],
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "risks": self.risks,
            "seniority": self.seniority,
            "notes": self.notes,
        }


def _role_title(m: MatchInput) -> tuple[float, str, bool]:
    title = title_key(m.job.title)
    # A broad "consultant" keyword must not turn licensed clinical work into a
    # business consulting match. Apply only to unrelated lane titles, preserving
    # explicit custom medical career lanes.
    clinical = (
        "coding consultant",
        "medical coder",
        "outpatient",
        "inpatient",
        "registered nurse",
        "consultant nursing",
        "nursing consultant",
        "physician",
    )
    if any(contains_term(title, term) for term in clinical) and not any(
        contains_term(title_key(kw), term) for kw in m.lane.title_keywords for term in clinical
    ):
        return 0.0, "Clinical or medical-coding title is outside this lane's role family.", False
    # Intervening words can change the occupation, not merely qualify it. Keep
    # explicit custom lanes for these families; don't match them by scattered words.
    for family in (
        "product marketing",
        "data annotation",
        "data labeling",
        "data labelling",
        "data entry",
    ):
        if contains_term(title, family) and not any(
            contains_term(title_key(kw), family) for kw in m.lane.title_keywords
        ):
            return 0.0, f"'{family}' is a different role family from this lane's keywords.", False
    for kw in m.lane.title_keywords:
        if contains_term(title, title_key(kw)):
            return 1.0, f"Title contains '{kw}'.", True
    for kw in m.lane.title_keywords:
        words = title_key(kw).split()
        if words and all(contains_term(title, w) for w in words):
            return 0.6, f"Title contains all words of '{kw}'.", True
    return 0.0, "Title doesn't match this lane's keywords.", False


def _skills(m: MatchInput) -> tuple[float | None, str, list[str], list[str]]:
    desc = m.job.description.lower() + " " + m.job.title.lower()
    lane_terms = list(dict.fromkeys(m.lane.required_skills + m.lane.preferred_skills))
    candidate = {s.lower(): s for s in m.profile.verified_skills}
    mentioned = [
        s for s in dict.fromkeys(lane_terms + list(candidate.values())) if contains_term(desc, s)
    ]
    if not mentioned:
        return None, "Posting doesn't mention any lane or profile skills.", [], []
    matched = [s for s in mentioned if s.lower() in candidate]
    missing = [s for s in mentioned if s.lower() not in candidate]
    required_missing = [
        s for s in m.lane.required_skills if contains_term(desc, s) and s.lower() not in candidate
    ]
    score = len(matched) / len(mentioned)
    if required_missing:
        score *= 0.5
    why = f"{len(matched)} of {len(mentioned)} skills in the posting are verified on your profile."
    if required_missing:
        why += f" Missing required: {', '.join(required_missing)} (halved)."
    return score, why, matched, missing


def _experience(m: MatchInput, mentioned: list[str]) -> tuple[float | None, str]:
    if not mentioned:
        return None, "No skills mentioned in the posting to look for evidence of."
    if not m.profile.has_verified_evidence:
        return 0.0, "No verified experience or projects on your profile yet."
    hits = [s for s in mentioned if contains_term(m.profile.evidence_text, s)]
    return (
        len(hits) / len(mentioned),
        f"Verified experience/projects show {len(hits)} of {len(mentioned)} posting skills"
        + (f" ({', '.join(hits)})." if hits else "."),
    )


def _seniority_score(level: str | None, allowed: tuple[str, ...]) -> tuple[float | None, str]:
    if level is None:
        return None, "Seniority couldn't be inferred."
    if level in allowed:
        return 1.0, f"Inferred {level}, which the lane allows."
    if not allowed:
        return 0.0, "Lane allows no seniority levels."
    idx = SENIORITY_ORDER.index(level)
    gaps = [abs(idx - SENIORITY_ORDER.index(a)) for a in allowed]
    return (
        (0.5, f"Inferred {level}, one level from what the lane allows.")
        if min(gaps) == 1
        else (0.0, f"Inferred {level}, well outside what the lane allows.")
    )


def _compensation(m: MatchInput) -> tuple[float | None, str]:
    lo, hi, floor = m.job.salary_min, m.job.salary_max, m.profile.salary_floor
    if lo is None and hi is None:
        return None, "Salary not disclosed. Counted as neutral, not as zero."
    if m.job.salary_interval and m.job.salary_interval not in ("year", "per-year-salary", "yearly"):
        return None, f"Salary stated per {m.job.salary_interval}; not compared to an annual floor."
    if floor is None:
        return None, "Set a salary floor on your profile to score compensation."
    top = hi if hi is not None else lo
    bottom = lo if lo is not None else hi
    assert top is not None and bottom is not None
    if top < floor:
        return 0.0, f"Top of range ({top:,}) is below your floor ({floor:,})."
    if bottom >= floor:
        return 1.0, f"Whole range is at or above your floor ({floor:,})."
    return 0.7, f"Range straddles your floor ({floor:,})."


def _preference(m: MatchInput) -> tuple[float | None, str]:
    if not m.lane.preferred_companies:
        return None, "No preferred companies set for this lane."
    for c in m.lane.preferred_companies:
        if contains_term(m.job.company, c):
            return 1.0, f"{m.job.company} is on your preferred list."
    return 0.5, "Not on your preferred list (neutral)."


def evaluate(m: MatchInput) -> MatchResult:
    weights = dict(m.lane.weights)
    guess = infer_seniority(m.job.title, m.job.description)

    filters = [
        status_filter(m.job),
        employment_filter(m.job, m.lane),
        excluded_terms_filter(m.job, m.lane),
        title_exclude_filter(m.job, m.lane),
        seniority_filter(guess, m.lane),
        location_filter(m.job, m.lane, m.profile),
        work_authorization_filter(m.job, m.profile),
    ]
    location = next(f for f in filters if f.name == "location")

    role_score, role_why, classified = _role_title(m)
    skill_score, skill_why, matched, missing = _skills(m)
    exp_score, exp_why = _experience(m, matched + missing)
    sen_score, sen_why = _seniority_score(guess.level, m.lane.seniority_allowed)
    loc_score = {"pass": 1.0, "fail": 0.0}.get(location.decision)
    comp_score, comp_why = _compensation(m)
    pref_score, pref_why = _preference(m)

    dims = [
        Dimension("role_title", weights["role_title"], role_score, role_why),
        Dimension("skills", weights["skills"], skill_score, skill_why),
        Dimension("experience", weights["experience"], exp_score, exp_why),
        Dimension("seniority", weights["seniority"], sen_score, sen_why),
        Dimension("location", weights["location"], loc_score, location.reason),
        Dimension("compensation", weights["compensation"], comp_score, comp_why),
        Dimension("preference", weights["preference"], pref_score, pref_why),
    ]
    total_weight = max(sum(d.weight for d in dims), 1)
    known_weight = sum(d.weight for d in dims if d.score is not None)
    total = round(sum(d.weight * d.effective for d in dims) / total_weight * 100)
    completeness = round(known_weight / total_weight * 100)

    risks = [f"{f.name.replace('_', ' ')}: {f.reason}" for f in filters if f.decision != "pass"]
    if comp_score is None and m.job.salary_min is None and m.job.salary_max is None:
        risks.append("Salary not disclosed.")
    notes = []
    if m.profile.unverified_skill_count:
        notes.append(f"{m.profile.unverified_skill_count} unverified skills were not counted.")

    eligibility = combine(filters)
    lead = {
        "pass": "Passes all hard filters",
        "fail": "Fails a hard filter",
        "unknown": "Needs review",
    }[eligibility]
    explanation = (
        f"{lead}. Score {total}/100 for {m.lane.name} with {completeness}% of the "
        f"weighted information available."
    )
    return MatchResult(
        classified=classified,
        eligibility=eligibility,
        score=total,
        completeness=completeness,
        dimensions=dims,
        filters=filters,
        matched_skills=matched,
        missing_skills=missing,
        risks=risks,
        seniority={
            "level": guess.level,
            "confidence": guess.confidence,
            "rationale": guess.rationale,
            "inferred": True,
        },
        explanation=explanation,
        input_hash=m.input_hash(),
        notes=notes,
    )
