"""Score jobs against enabled role lanes and persist explainable results."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Company, Job, JobLaneMatch, MatchOverride, RoleLane
from careeros.modules.events.service import record_event
from careeros.modules.matching.inputs import (
    ALGORITHM_VERSION,
    JobInput,
    LaneInput,
    MatchInput,
    ProfileInput,
)
from careeros.modules.matching.scoring import evaluate
from careeros.modules.profile import service as profile_service

Eligibility = Literal["pass", "fail", "unknown"]


def build_profile_input(session: Session) -> ProfileInput:
    profile = profile_service.get_profile(session)
    if profile is None:
        return ProfileInput()
    skills = profile_service.list_skills(session, profile.id)
    verified_skills = tuple(s.name for s in skills if s.verified_status == "verified")
    evidence: list[str] = []
    for e in profile_service.list_experience(session, profile.id):
        if e.verified_status == "verified":
            evidence += [e.title, e.organization, e.description or ""]
    for p in profile_service.list_projects(session, profile.id):
        if p.verified_status == "verified":
            evidence += [
                p.name,
                p.description or "",
                " ".join(p.technologies_json),
                " ".join(p.outcomes_json),
            ]
    reloc = profile.relocation_preferences_json or {}
    wa = profile_service.get_work_authorization(session, profile.id)
    needs = "unknown"
    if wa is not None and wa.verified_at is not None:  # only confirmed answers count
        flags = {wa.requires_sponsorship_now, wa.requires_sponsorship_future}
        needs = "yes" if "yes" in flags else ("no" if flags == {"no"} else "unknown")
    return ProfileInput(
        verified_skills=verified_skills,
        unverified_skill_count=len(skills) - len(verified_skills),
        evidence_text=" ".join(evidence).lower(),
        has_verified_evidence=bool(evidence),
        current_location=profile.current_location,
        open_to_relocation=reloc.get("open_to_relocation"),
        relocation_locations=tuple(reloc.get("locations", [])),
        salary_floor=profile.salary_floor,
        needs_sponsorship=needs,
    )


def build_lane_input(lane: RoleLane) -> LaneInput:
    r = profile_service.lane_rules(lane)
    w = profile_service.lane_weights(lane)
    return LaneInput(
        name=lane.name,
        title_keywords=tuple(r.title_keywords),
        title_exclude=tuple(r.title_exclude),
        required_skills=tuple(r.required_skills),
        preferred_skills=tuple(r.preferred_skills),
        seniority_allowed=tuple(r.seniority_allowed),
        employment_types=tuple(r.employment_types),
        excluded_terms=tuple(r.excluded_terms),
        preferred_locations=tuple(r.preferred_locations),
        remote_ok=r.remote_ok,
        preferred_companies=tuple(r.preferred_companies),
        weights=tuple(sorted(w.model_dump().items())),
    )


def build_job_input(
    job: Job,
    company: str,
    session: Session | None = None,
    *,
    companies_with_evidence: set[str] | None = None,
) -> JobInput:
    policy, note = "unknown", None
    if session is not None and (
        companies_with_evidence is None or job.company_id in companies_with_evidence
    ):
        from careeros.modules.research.service import employer_policy

        summary = employer_policy(session, job.company_id, job.id)
        policy, note = summary.status, summary.note
    return JobInput(
        employer_policy=policy,
        employer_policy_note=note,
        title=job.title,
        company=company,
        location_text=job.location_text,
        workplace_type=job.workplace_type,
        employment_type=job.employment_type,
        description=job.description_text,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_interval=job.salary_interval,
        status=job.status,
    )


@dataclass
class ScoreSummary:
    jobs: int = 0
    scored: int = 0
    unchanged: int = 0
    passing: int = 0
    needs_review: int = 0
    failing: int = 0


def score_jobs(
    session: Session, job_ids: list[str] | None = None, *, commit_every: int | None = None
) -> ScoreSummary:
    """Score jobs (all, or the given ids) for every enabled lane. Skips unchanged inputs.

    With `commit_every`, results are committed in batches of that many jobs so the database
    write lock is never held for long (the dashboard stays responsive during big rescores).
    """
    from careeros.db.models import Evidence

    lanes = [
        (lane, build_lane_input(lane))
        for lane in profile_service.list_lanes(session, enabled_only=True)
    ]
    enabled_ids = [lane.id for lane, _ in lanes]
    profile = build_profile_input(session)
    with_evidence = set(
        session.scalars(
            select(Evidence.company_id).where(Evidence.reviewer_status == "accepted").distinct()
        )
    )

    stale = delete(JobLaneMatch).where(JobLaneMatch.role_lane_id.not_in(enabled_ids))
    if job_ids is not None:
        stale = stale.where(JobLaneMatch.job_id.in_(job_ids))
    session.execute(stale)
    if commit_every:
        session.commit()

    stmt = select(Job, Company.canonical_name).join(Company, Company.id == Job.company_id)
    if job_ids is not None:
        stmt = stmt.where(Job.id.in_(job_ids))
    rows = session.execute(stmt.order_by(Job.id)).all()

    existing: dict[str, dict[str, JobLaneMatch]] = {}
    match_stmt = select(JobLaneMatch)
    if job_ids is not None:
        match_stmt = match_stmt.where(JobLaneMatch.job_id.in_(job_ids))
    for m in session.scalars(match_stmt):
        existing.setdefault(m.job_id, {})[m.role_lane_id] = m

    rank = {"pass": 0, "unknown": 1, "fail": 2}
    summary = ScoreSummary()
    for n, (job, company) in enumerate(rows, start=1):
        summary.jobs += 1
        current_rows = existing.get(job.id, {})
        job_input = build_job_input(job, company, session, companies_with_evidence=with_evidence)
        best: str | None = None
        for lane, lane_input in lanes:
            mi = MatchInput(job=job_input, lane=lane_input, profile=profile)
            current = current_rows.get(lane.id)
            if (
                current is not None
                and current.input_hash == mi.input_hash()
                and current.algorithm_version == ALGORITHM_VERSION
            ):
                summary.unchanged += 1
                eligibility = current.eligibility
                classified = current.classified
            else:
                result = evaluate(mi)
                row = current or JobLaneMatch(job_id=job.id, role_lane_id=lane.id)
                row.classified = result.classified
                row.eligibility = result.eligibility
                row.score = result.score
                row.completeness = result.completeness
                row.score_breakdown_json = result.breakdown()
                row.hard_filter_results_json = [f.to_dict() for f in result.filters]
                row.explanation = result.explanation
                row.algorithm_version = result.algorithm_version
                row.input_hash = result.input_hash
                row.created_at = utcnow()
                if current is None:
                    session.add(row)
                summary.scored += 1
                eligibility, classified = result.eligibility, result.classified
            if classified and (best is None or rank[eligibility] < rank[best]):
                best = eligibility
        if best == "pass":
            summary.passing += 1
        elif best == "unknown":
            summary.needs_review += 1
        elif best == "fail":
            summary.failing += 1
        if commit_every and n % commit_every == 0:
            session.commit()
    session.flush()
    if summary.scored:
        record_event(
            session,
            "job.scored",
            f"Scored {summary.jobs} jobs: {summary.passing} pass, "
            f"{summary.needs_review} need review, {summary.failing} filtered out",
            metadata={
                "scored": summary.scored,
                "unchanged": summary.unchanged,
                "algorithm_version": ALGORITHM_VERSION,
            },
        )
    return summary


# ---------- reading results ----------


@dataclass
class LaneMatchView:
    lane_id: str
    lane_name: str
    match: JobLaneMatch
    override: MatchOverride | None

    @property
    def effective_eligibility(self) -> str:
        if self.override and self.override.eligibility:
            return self.override.eligibility
        return self.match.eligibility

    @property
    def effective_score(self) -> int:
        if self.override and self.override.score is not None:
            return self.override.score
        return self.match.score


def matches_for_job(session: Session, job_id: str) -> list[LaneMatchView]:
    rows = session.execute(
        select(JobLaneMatch, RoleLane)
        .join(RoleLane, RoleLane.id == JobLaneMatch.role_lane_id)
        .where(JobLaneMatch.job_id == job_id, RoleLane.enabled.is_(True))
    ).all()
    overrides = {
        o.role_lane_id: o
        for o in session.scalars(select(MatchOverride).where(MatchOverride.job_id == job_id))
    }
    views = [LaneMatchView(lane.id, lane.name, m, overrides.get(lane.id)) for m, lane in rows]
    return sorted(views, key=lambda v: (not v.match.classified, -v.effective_score, v.lane_name))


def best_matches(session: Session, job_ids: list[str]) -> dict[str, LaneMatchView]:
    """Best classified lane per job (falls back to best overall if none classified)."""
    if not job_ids:
        return {}
    rows = session.execute(
        select(JobLaneMatch, RoleLane)
        .join(RoleLane, RoleLane.id == JobLaneMatch.role_lane_id)
        .where(JobLaneMatch.job_id.in_(job_ids), RoleLane.enabled.is_(True))
    ).all()
    overrides = {
        (o.job_id, o.role_lane_id): o
        for o in session.scalars(select(MatchOverride).where(MatchOverride.job_id.in_(job_ids)))
    }
    best: dict[str, LaneMatchView] = {}
    for m, lane in rows:
        view = LaneMatchView(lane.id, lane.name, m, overrides.get((m.job_id, lane.id)))
        cur = best.get(m.job_id)
        key = (view.match.classified, view.effective_eligibility != "fail", view.effective_score)
        if cur is None or key > (
            cur.match.classified,
            cur.effective_eligibility != "fail",
            cur.effective_score,
        ):
            best[m.job_id] = view
    return best


def lane_matches(session: Session, job_ids: list[str], lane_id: str) -> dict[str, LaneMatchView]:
    if not job_ids:
        return {}
    rows = session.execute(
        select(JobLaneMatch, RoleLane)
        .join(RoleLane, RoleLane.id == JobLaneMatch.role_lane_id)
        .where(JobLaneMatch.job_id.in_(job_ids), JobLaneMatch.role_lane_id == lane_id)
    ).all()
    overrides = {
        o.job_id: o
        for o in session.scalars(
            select(MatchOverride).where(
                MatchOverride.job_id.in_(job_ids), MatchOverride.role_lane_id == lane_id
            )
        )
    }
    return {
        m.job_id: LaneMatchView(lane.id, lane.name, m, overrides.get(m.job_id)) for m, lane in rows
    }


@dataclass
class MatchCounts:
    passing: int
    needs_review: int
    filtered_out: int
    unscored: int
    # Which hard filter most often leaves jobs at "needs review", e.g. ("work authorization", 61).
    top_blocker: tuple[str, int] | None = None


def match_counts(session: Session) -> MatchCounts:
    ids = list(
        session.scalars(
            select(Job.id).where(Job.status == "active", Job.triage_status != "rejected")
        )
    )
    best = best_matches(session, ids)
    c = MatchCounts(0, 0, 0, 0)
    blockers: dict[str, int] = {}
    for job_id in ids:
        view = best.get(job_id)
        if view is None or not view.match.classified:
            c.unscored += 1
        elif view.effective_eligibility == "pass":
            c.passing += 1
        elif view.effective_eligibility == "unknown":
            c.needs_review += 1
            for f in view.match.hard_filter_results_json:
                if f.get("decision") == "unknown":
                    blockers[f["name"]] = blockers.get(f["name"], 0) + 1
        else:
            c.filtered_out += 1
    if blockers:
        name, n = max(blockers.items(), key=lambda kv: kv[1])
        c.top_blocker = (name.replace("_", " "), n)
    return c


# ---------- overrides ----------


class OverrideError(ValueError):
    pass


def set_override(
    session: Session,
    job_id: str,
    lane_id: str,
    *,
    eligibility: str | None,
    score: int | None,
    reason: str | None,
) -> MatchOverride:
    reason = (reason or "").strip()
    if not reason:
        raise OverrideError("An override needs a reason.")
    if len(reason) > 1000:
        raise OverrideError("Reason is too long (1000 characters max).")
    if eligibility not in (None, "pass", "fail"):
        raise OverrideError("Eligibility override must be pass or fail.")
    if score is not None and not 0 <= score <= 100:
        raise OverrideError("Score override must be between 0 and 100.")
    if eligibility is None and score is None:
        raise OverrideError("Choose an eligibility or a score to override.")
    if session.get(Job, job_id) is None or session.get(RoleLane, lane_id) is None:
        raise LookupError("Job or lane not found")
    row = session.scalars(
        select(MatchOverride).where(
            MatchOverride.job_id == job_id, MatchOverride.role_lane_id == lane_id
        )
    ).first()
    if row is None:
        row = MatchOverride(job_id=job_id, role_lane_id=lane_id, reason=reason)
        session.add(row)
    row.eligibility, row.score, row.reason, row.created_at = eligibility, score, reason, utcnow()
    session.flush()
    record_event(
        session,
        "match.overridden",
        "Match overridden by user",
        entity_type="job",
        entity_id=job_id,
        metadata={"lane_id": lane_id, "eligibility": eligibility, "score": score},
    )
    return row


def clear_override(session: Session, job_id: str, lane_id: str) -> None:
    session.execute(
        delete(MatchOverride).where(
            MatchOverride.job_id == job_id, MatchOverride.role_lane_id == lane_id
        )
    )
    record_event(
        session,
        "match.override_cleared",
        "Match override removed",
        entity_type="job",
        entity_id=job_id,
        metadata={"lane_id": lane_id},
    )


def has_stale_scores(session: Session) -> bool:
    """True if any stored match was produced by an older algorithm version."""
    stmt = select(JobLaneMatch.id).where(JobLaneMatch.algorithm_version != ALGORITHM_VERSION)
    return session.scalars(stmt.limit(1)).first() is not None
