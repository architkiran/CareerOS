"""Career OS 2.0 eligibility engine: one explainable verdict per job. Pure functions.

Hard gates run first and a ranking score can never override them (mission spec 7.1).

    rejected   at least one hard gate failed; the reason is kept for audit
    eligible   every gate passed and sponsorship evidence is Level A or B
    research   every gate passed except sponsorship, which is Level C or U
    review     some other hard criterion could not be determined from the source

Each check is pass, assumed, unknown or fail. "assumed" means the source does not state the
fact and nothing contradicts the default; it is shown to the candidate as an assumption, never
hidden. Rules are documented in docs/ELIGIBILITY_RULES.md and covered by tests.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from careeros.modules.matching.filters import (
    _employment_from_description,
    looks_non_us,
    looks_us,
)
from careeros.modules.matching.seniority import infer_seniority
from careeros.modules.matching.text import contains_term, excerpt
from careeros.modules.sponsorship.levels import Assessment

ENGINE_VERSION = "elig-v1"
Decision = Literal["pass", "assumed", "unknown", "fail"]
Verdict = Literal["eligible", "research", "review", "rejected"]

# Ordered: the first family whose pattern matches the title wins.
ROLE_FAMILIES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "tech_systems",
        "Technology-adjacent and systems",
        re.compile(
            r"business systems analyst|systems analyst|\bit analyst|technology analyst|"
            r"technical business analyst|implementation (?:analyst|consultant|specialist|"
            r"associate)|solutions analyst|technical program analyst|"
            r"technology operations analyst|technology consultant"
        ),
    ),
    (
        "data_engineering",
        "Data engineering",
        re.compile(
            r"data engineer|analytics engineer|etl (?:analyst|developer)|"
            r"data integration|database analyst|data platform|data (?:&|and) ai engineer"
        ),
    ),
    (
        "product",
        "Product",
        re.compile(
            r"product analyst|associate product manager|\bapm\b|rotational product manager|"
            r"junior product manager|product operations|product ops|product strategy|"
            r"product insights|product data analyst|technical product analyst|"
            r"product manage(?:r|ment)\b"
        ),
    ),
    (
        "finance_risk",
        "Finance and risk",
        re.compile(
            r"financial analyst|finance analyst|fp&a|risk analyst|credit analyst|"
            r"treasury analyst|investment (?:operations|analyst)|financial operations|credit risk|"
            r"compliance analyst|regulatory analyst|fund (?:accountant|operations)|"
            r"portfolio (?:analyst|operations)|finance associate|"
            r"(?:finance|financial).{0,25}(?:rotational|development) program"
        ),
    ),
    (
        "data_bi",
        "Data and business intelligence",
        re.compile(
            r"data analyst|bi analyst|business intelligence|reporting analyst|"
            r"analytics (?:analyst|associate|specialist)|insights analyst|data quality|"
            r"data operations|decision (?:analyst|scientist)|data (?:&|and) analytics|"
            r"analyst,? (?:data|analytics)|data analytics|data science analyst|"
            r"data management analyst|data governance analyst|data associate|"
            r"operations research|business insights|insights (?:associate|assistant)|"
            r"(?:data|analytics) consultant|\banalytics\b"
        ),
    ),
    (
        "business_strategy",
        "Business and strategy",
        re.compile(
            r"business analyst|strategy analyst|operations analyst|business operations|"
            r"bizops|management analyst|program analyst|process analyst|"
            r"transformation analyst|consulting analyst|associate consultant|"
            r"strategy (?:&|and) operations|business associate|"
            r"(?:analyst|associate) (?:development|rotational) program|strategy associate|"
            r"revenue operations analyst|sales operations analyst|pricing analyst|"
            r"supply chain analyst|marketing analyst|growth analyst|"
            r"(?:business|strategy|management) consultant"
        ),
    ),
    ("data_science", "Data science", re.compile(r"data scientist")),
]
_GENERIC_ANALYST = re.compile(r"\banalyst\b")

_SENIOR_TITLE = re.compile(
    r"\b(senior|sr|staff|principal|lead|director|vp|vice president|head of|chief|architect|"
    r"iii|iv|expert|distinguished|fellow)\b"
)
_MANAGER_TITLE = re.compile(r"\bmanager\b")
_ENTRY_MANAGER = re.compile(
    r"associate product manager|junior product manager|rotational|new[- ]grad|university|"
    r"early[- ]career|in[- ]training|campus|\bapm\b|entry[- ]level|product management"
)
_CITY_ALIASES = re.compile(r"\b(sf|nyc|la|dc|bay area|silicon valley)\b", re.IGNORECASE)
_LEVEL_TWO = re.compile(r"\b(ii|2)\s*$|\blevel\s*(?:ii|2)\b")
_NOT_FULL_TIME_TITLE = re.compile(
    r"\b(intern|interns|internship|co-?op|contract|contractor|temporary|temp|part[- ]time|"
    r"seasonal|fellowship|apprentice(?:ship)?|volunteer|unpaid|freelance|per diem)\b"
)
_FIXED_TERM = re.compile(
    r"\b(?:fixed[- ]term|\d{1,2}[- ]month\s+(?:contract|term|assignment|program|role)|"
    r"limited[- ]term)\b"
)
_ENTRY_SIGNAL = re.compile(
    r"new[- ]grad(?:uate)?s?\b|recent[- ]grad(?:uate)?s?\b|entry[- ]level|early[- ]career|"
    r"university grad(?:uate)?|campus (?:hire|program|recruit)|class of 202[67]|"
    r"graduating (?:in|between|by)|\b0\s*(?:-|–|to)\s*[12]\s+years?|"
    r"no (?:prior )?(?:professional |work )?experience (?:is )?(?:required|necessary|needed)|"
    r"graduate (?:program|scheme|analyst)|rotational (?:program|analyst)|"
    r"less than (?:1|one|2|two) years?|up to (?:1|one) years?"
)
_ENTRY_TITLE = re.compile(
    r"\b(junior|jr|entry[- ]level|new[- ]grad(?:uate)?|graduate|early[- ]career|"
    r"university|campus|rotational|analyst i|associate i|class of 202[67]|202[67])\b"
)
_STATE_LIMIT = re.compile(
    r"(?:must|only|required to)\s[^.\n]{0,50}(?:reside|live|be located|be based)\s+in\s+"
    r"(?:one of\s+)?(?:the following\s+(?:states|locations)|[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)+|"
    r"[A-Z]{2}(?:,\s*[A-Z]{2})+)|not\s+(?:able|eligible)\s+to\s+hire\s+in\s+[^.\n]{3,80}"
)
_US_IN_TEXT = re.compile(r"united states|\bu\.s\.|\busa\b|\bus[- ]based\b|within the us\b", re.I)
_BOSTON = re.compile(r"boston|cambridge, ma|massachusetts|\bma\b|waltham|somerville|quincy", re.I)


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    decision: Decision
    reason: str
    evidence: str | None = None


@dataclass(frozen=True)
class JobFacts:
    title: str
    company: str
    location_text: str | None
    workplace_type: str | None
    employment_type: str | None
    description: str
    status: str
    last_seen_at: datetime
    posted_at: datetime | None
    first_seen_at: datetime
    has_official_source: bool
    on_new_grad_list: bool = False


@dataclass(frozen=True)
class CandidateRules:
    needs_sponsorship: bool | None  # None = the candidate has not confirmed it
    open_to_relocation: bool | None = None
    excluded_states: tuple[str, ...] = ()
    primary_families: tuple[str, ...] = ("data_bi", "data_engineering")
    verified_skills: tuple[str, ...] = ()
    stale_after_days: int = 4


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    reason: str
    next_action: str
    role_family: str | None
    role_family_label: str | None
    checks: tuple[Check, ...]
    sponsorship_level: str
    fit: str | None = None
    fit_reasons: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    rank: int = 0
    engine_version: str = field(default=ENGINE_VERSION)

    def checks_json(self) -> list[dict[str, Any]]:
        return [asdict(c) for c in self.checks]


def classify_role(title: str) -> tuple[str | None, str | None]:
    low = title.lower()
    for key, label, pattern in ROLE_FAMILIES:
        if pattern.search(low):
            return key, label
    return None, None


def _role_check(title: str) -> tuple[Check, str | None, str | None]:
    key, label = classify_role(title)
    if key:
        return Check("role", "Target role family", "pass", f"{label} role."), key, label
    if _GENERIC_ANALYST.search(title.lower()):
        return (
            Check(
                "role",
                "Target role family",
                "unknown",
                "An analyst title outside your named role families. Decide if it is relevant.",
                title,
            ),
            None,
            None,
        )
    return (
        Check("role", "Target role family", "fail", "Outside your target role families.", title),
        None,
        None,
    )


def _open_check(job: JobFacts, rules: CandidateRules, now: datetime) -> Check:
    if job.status != "active":
        return Check("open", "Currently open", "fail", "The source no longer lists this job.")
    age = now - job.last_seen_at
    seen = job.last_seen_at.strftime("%b %d")
    if age > timedelta(days=rules.stale_after_days):
        return Check(
            "open",
            "Currently open",
            "unknown",
            f"Last seen listed on {seen}; not re-verified since. It may have closed.",
        )
    return Check("open", "Currently open", "pass", f"Listed by the source as of {seen}.")


def _geography_check(job: JobFacts, rules: CandidateRules) -> Check:
    loc = (job.location_text or "").strip()
    label = "US work location"
    remote = job.workplace_type == "remote" or (bool(loc) and contains_term(loc, "remote"))
    if loc and looks_non_us(loc):
        return Check("geography", label, "fail", "Location is outside the United States.", loc)
    limit = _STATE_LIMIT.search(job.description) if remote else None
    if limit:
        return Check(
            "geography",
            label,
            "unknown",
            "Remote, but the posting restricts where you may live. Check the listed states.",
            excerpt(job.description, limit),
        )
    if loc and (looks_us(loc) or _CITY_ALIASES.search(loc)):
        for state in rules.excluded_states:
            if contains_term(loc, state) and ";" not in loc:
                return Check("geography", label, "fail", f"Only in {state}, which you excluded.")
        kind = "US-remote" if remote else "US location"
        if rules.open_to_relocation is False and not remote and not _BOSTON.search(loc):
            return Check(
                "geography", label, "fail", "Outside Boston and you are not relocating.", loc
            )
        return Check("geography", label, "pass", f"{kind}: {loc}.", loc)
    if remote:
        if _US_IN_TEXT.search(job.description):
            return Check(
                "geography", label, "pass", "Remote; the posting refers to the United States."
            )
        return Check(
            "geography",
            label,
            "unknown",
            "Remote, but the source does not say which countries are covered.",
            loc or None,
        )
    if not loc:
        return Check("geography", label, "unknown", "The source does not state a location.")
    return Check(
        "geography", label, "unknown", "Could not confirm this location is in the US.", loc
    )


def _employment_check(job: JobFacts) -> tuple[Check, list[str]]:
    label = "Full-time employment"
    flags: list[str] = []
    title_hit = _NOT_FULL_TIME_TITLE.search(job.title.lower())
    if title_hit:
        return (
            Check(
                "employment",
                label,
                "fail",
                f"Title says '{title_hit.group(0)}'; you want full-time roles only.",
                job.title,
            ),
            flags,
        )
    fixed = _FIXED_TERM.search(job.description.lower())
    if fixed:
        flags.append(f"Fixed-term wording in the posting: '{fixed.group(0)}'. Not permanent.")
    if job.employment_type is not None:
        stated = job.employment_type.replace("_", " ")
        decision: Decision = "pass" if job.employment_type == "full_time" else "fail"
        return Check("employment", label, decision, f"Source states {stated}."), flags
    kinds, matches = _employment_from_description(job.description)
    if kinds == {"full_time"}:
        quote = excerpt(job.description, matches["full_time"], 60)
        return Check("employment", label, "pass", "Posting says full-time.", quote), flags
    if kinds:
        found = ", ".join(sorted(k.replace("_", " ") for k in kinds))
        quote = excerpt(job.description, next(iter(matches.values())), 60)
        return (
            Check("employment", label, "unknown", f"Posting mentions {found}. Check it.", quote),
            flags,
        )
    return (
        Check(
            "employment",
            label,
            "assumed",
            "Not stated by the source. No internship, contract or part-time wording found.",
        ),
        flags,
    )


def _stage_check(job: JobFacts) -> Check:
    label = "Early career (0 to 1 years)"
    low_title = job.title.lower()
    senior = _SENIOR_TITLE.search(low_title)
    if senior:
        return Check("stage", label, "fail", f"Title says '{senior.group(0)}'.", job.title)
    if _MANAGER_TITLE.search(low_title) and not _ENTRY_MANAGER.search(low_title):
        if job.on_new_grad_list and not job.description:
            return Check(
                "stage",
                label,
                "unknown",
                "Manager title, though it appears on a new-graduate list. Read the posting.",
                job.title,
            )
        return Check("stage", label, "fail", "Manager title without an entry pathway.", job.title)
    guess = infer_seniority(job.title, job.description)
    years = guess.min_years
    low_desc = job.description.lower()
    entry_title = _ENTRY_TITLE.search(low_title)
    entry_text = _ENTRY_SIGNAL.search(low_desc) or _ENTRY_SIGNAL.search(low_title)
    explicit = guess.confidence == "high" and years is not None
    if years is not None and years >= 3:
        if entry_title or entry_text:
            return Check(
                "stage",
                label,
                "unknown",
                f"New-graduate wording, but the posting also mentions {years}+ years. "
                "Read the requirement.",
                guess.rationale,
            )
        if explicit:
            return Check("stage", label, "fail", f"Requires {years}+ years.", guess.rationale)
        return Check(
            "stage",
            label,
            "unknown",
            f"Mentions {years}+ years; unclear if required.",
            guess.rationale,
        )
    if years == 2:
        if entry_title or entry_text:
            return Check(
                "stage",
                label,
                "unknown",
                "Entry-level wording, but 2 years are mentioned. Read the requirement.",
                guess.rationale,
            )
        return Check("stage", label, "unknown", "Mentions 2 years of experience.", guess.rationale)
    if years is not None:  # 0 or 1
        return Check("stage", label, "pass", f"Asks for {years} year(s) or less.", guess.rationale)
    if entry_text:
        m = entry_text
        src = job.description if _ENTRY_SIGNAL.search(low_desc) else job.title
        return Check(
            "stage",
            label,
            "pass",
            "The posting describes an entry-level pathway.",
            excerpt(src, m, 60),
        )
    if entry_title:
        return Check("stage", label, "pass", f"Title says '{entry_title.group(0)}'.", job.title)
    if _LEVEL_TWO.search(low_title):
        return Check("stage", label, "unknown", "Level II titles usually expect prior experience.")
    if job.on_new_grad_list and not job.description:
        return Check(
            "stage",
            label,
            "assumed",
            "Listed on a curated new-graduate list (third party). The requirement itself "
            "is not verified until the employer posting is read.",
        )
    if not job.description:
        return Check(
            "stage", label, "unknown", "No posting text available to read the requirement."
        )
    return Check(
        "stage",
        label,
        "unknown",
        "The posting states no experience requirement and no entry-level pathway. "
        "An analyst or associate title alone is not proof of entry level.",
    )


def _authorization_check(sponsorship: Assessment, rules: CandidateRules) -> Check:
    label = "Sponsorship pathway"
    quote = next((i.quote for i in sponsorship.items if i.quote), None)
    if rules.needs_sponsorship is None:
        return Check(
            "authorization",
            label,
            "unknown",
            "Your sponsorship need is not confirmed in your profile yet.",
        )
    if rules.needs_sponsorship is False:
        return Check("authorization", label, "pass", "Your profile says no sponsorship needed.")
    level = sponsorship.level
    if level == "D":
        return Check("authorization", label, "fail", sponsorship.summary, quote)
    if level == "A":
        return Check("authorization", label, "pass", sponsorship.summary, quote)
    if level == "B":
        return Check(
            "authorization",
            label,
            "pass",
            "Employer-level history only. Role sponsorship is unconfirmed; ask the recruiter.",
        )
    return Check("authorization", label, "unknown", sponsorship.summary)


def _fit(
    job: JobFacts,
    rules: CandidateRules,
    family: str | None,
    level: str,
    now: datetime,
) -> tuple[str, list[str], list[str], int]:
    points, reasons, gaps = 0, [], []
    if family in rules.primary_families:
        points += 2
        reasons.append("One of your primary role families.")
    elif family:
        points += 1
        reasons.append("One of your secondary role families.")
    if job.description:
        low = job.description.lower()
        hits = [s for s in rules.verified_skills if contains_term(low, s)]
        if len(hits) >= 4:
            points += 2
        elif len(hits) >= 2:
            points += 1
        if hits:
            reasons.append("Posting names skills you have verified: " + ", ".join(hits[:6]) + ".")
        else:
            gaps.append("None of your verified skills appear in the posting text.")
    else:
        gaps.append("No posting text yet, so skills could not be compared.")
    if level == "A":
        points += 2
        reasons.append("Posting states sponsorship support.")
    elif level == "B":
        points += 1
        reasons.append("Employer has LCA history (role unconfirmed).")
    published = job.posted_at
    if published and now - published <= timedelta(days=7):
        points += 1
        reasons.append(f"Published {max((now - published).days, 0)} day(s) ago.")
    loc = job.location_text or ""
    if _BOSTON.search(loc) or job.workplace_type == "remote":
        points += 1
        reasons.append("Boston area or remote.")
    category = "Strong" if points >= 5 else "Good" if points >= 3 else "Stretch"
    return category, reasons, gaps, points


def evaluate(
    job: JobFacts, rules: CandidateRules, sponsorship: Assessment, now: datetime
) -> Result:
    role, family, family_label = _role_check(job.title)
    employment, flags = _employment_check(job)
    checks = (
        role,
        _open_check(job, rules, now),
        _geography_check(job, rules),
        employment,
        _stage_check(job),
        _authorization_check(sponsorship, rules),
    )
    if not job.has_official_source:
        flags.append("Known only through a third-party list; confirm on the employer's page.")
    if sponsorship.contradictions:
        flags.extend(sponsorship.contradictions)
    failed = [c for c in checks if c.decision == "fail"]
    unknown = [c for c in checks if c.decision == "unknown"]
    level = sponsorship.level
    if failed:
        return Result(
            "rejected",
            f"{failed[0].label}: {failed[0].reason}",
            "No action. Kept for audit.",
            family,
            family_label,
            checks,
            level,
            flags=tuple(flags),
        )
    fit, reasons, gaps, points = _fit(job, rules, family, level, now)
    rank = points * 100 + {"A": 30, "B": 20, "C": 5}.get(level, 0)
    if unknown:
        only_sponsorship = all(c.key == "authorization" for c in unknown)
        verdict: Verdict = "research" if only_sponsorship else "review"
        reason = "; ".join(f"{c.label}: {c.reason}" for c in unknown[:2])
        action = (
            "Sponsorship is unverified. Ask the recruiter before investing in an application: "
            + (sponsorship.recruiter_question or "")
            if only_sponsorship
            else "Open the original posting and confirm: "
            + ", ".join(c.label.lower() for c in unknown)
            + "."
        )
        return Result(
            verdict,
            reason,
            action,
            family,
            family_label,
            checks,
            level,
            fit,
            tuple(reasons),
            tuple(gaps),
            tuple(flags),
            rank - (0 if only_sponsorship else 50),
        )
    action = "Review the original posting and apply on the employer's site."
    if level == "B":
        action += " Ask the recruiter: " + (sponsorship.recruiter_question or "")
    return Result(
        "eligible",
        "Passes every hard rule; sponsorship evidence Level " + level + ".",
        action,
        family,
        family_label,
        checks,
        level,
        fit,
        tuple(reasons),
        tuple(gaps),
        tuple(flags),
        rank,
    )
