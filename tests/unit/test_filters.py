import pytest

from careeros.modules.matching.filters import (
    FilterResult,
    combine,
    employment_filter,
    excluded_terms_filter,
    location_filter,
    looks_us,
    seniority_filter,
    status_filter,
    title_exclude_filter,
    work_authorization_filter,
)
from careeros.modules.matching.seniority import SeniorityGuess
from tests.matching_helpers import job, lane, profile


def test_employment() -> None:
    assert employment_filter(job(), lane()).decision == "pass"
    assert employment_filter(job(employment_type="contract"), lane()).decision == "fail"
    r = employment_filter(job(employment_type=None), lane())
    assert r.decision == "unknown" and "doesn't state" in r.reason


def test_excluded_terms_on_title_only() -> None:
    assert excluded_terms_filter(job(title="Data Analyst Intern"), lane()).decision == "fail"
    assert (
        excluded_terms_filter(job(description="contract to hire possible"), lane()).decision
        == "pass"
    )
    assert excluded_terms_filter(job(title="International Data Analyst"), lane()).decision == "pass"


def test_title_exclusions() -> None:
    assert title_exclude_filter(job(title="Senior Data Analyst"), lane()).decision == "fail"
    assert title_exclude_filter(job(title="Data Analyst"), lane()).decision == "pass"


@pytest.mark.parametrize(
    ("guess", "expected"),
    [
        (SeniorityGuess("entry", "high", "x"), "pass"),
        (SeniorityGuess("senior", "high", "x"), "fail"),
        (SeniorityGuess("senior", "medium", "x"), "unknown"),
        (SeniorityGuess(None, None, "x"), "unknown"),
    ],
)
def test_seniority(guess: SeniorityGuess, expected: str) -> None:
    assert seniority_filter(guess, lane()).decision == expected


@pytest.mark.parametrize(
    ("loc", "wp", "prof", "expected"),
    [
        ("Boston, MA", None, {}, "pass"),
        ("New York, NY", None, {}, "pass"),  # NYC alias in relocation list
        ("Austin, TX", None, {"open_to_relocation": True}, "pass"),
        ("Austin, TX", None, {"open_to_relocation": False, "relocation_locations": ()}, "fail"),
        ("Austin, TX", None, {"open_to_relocation": None, "relocation_locations": ()}, "unknown"),
        ("London, UK", None, {"open_to_relocation": True}, "unknown"),
        ("Remote", "remote", {}, "pass"),
        (None, None, {}, "unknown"),
    ],
)
def test_location(loc: str | None, wp: str | None, prof: dict, expected: str) -> None:  # type: ignore[type-arg]
    assert (
        location_filter(job(location_text=loc, workplace_type=wp), lane(), profile(**prof)).decision
        == expected
    )


def test_remote_rejected_when_lane_disallows() -> None:
    assert (
        location_filter(job(workplace_type="remote"), lane(remote_ok=False), profile()).decision
        == "fail"
    )


def test_looks_us() -> None:
    assert looks_us("Chicago, IL") and looks_us("Remote - United States") and looks_us("New York")
    assert not looks_us("Toronto, ON") and not looks_us("Bangalore, India")


@pytest.mark.parametrize(
    ("text", "need", "expected"),
    [
        ("We do not sponsor visas for this role.", "yes", "fail"),
        ("We are unable to provide visa sponsorship.", "yes", "fail"),
        ("No sponsorship available.", "yes", "fail"),
        ("Candidates must be authorized to work without sponsorship.", "yes", "fail"),
        ("We do not sponsor visas for this role.", "no", "pass"),
        ("We do not sponsor visas for this role.", "unknown", "unknown"),
        ("Must be a U.S. citizen.", "no", "unknown"),  # citizenship ≠ no-sponsorship-needed
        ("Must be a U.S. citizen.", "yes", "fail"),
        ("Active secret clearance required.", "no", "unknown"),
        ("Visa sponsorship is available for this position.", "yes", "pass"),
        ("We will sponsor qualified candidates.", "yes", "pass"),
        ("Sponsorship is not available.", "yes", "fail"),
        ("Great benefits and a hybrid schedule.", "yes", "unknown"),
    ],
)
def test_work_authorization(text: str, need: str, expected: str) -> None:
    r = work_authorization_filter(job(description=text), profile(needs_sponsorship=need))
    assert r.decision == expected
    if expected != "unknown" or "sponsor" in text.lower() or "citizen" in text.lower():
        assert r.evidence or r.decision == "unknown"


def test_work_authorization_quotes_the_posting() -> None:
    r = work_authorization_filter(
        job(description="Intro. We do not sponsor visas. Outro."), profile(needs_sponsorship="yes")
    )
    assert r.evidence and "do not sponsor" in r.evidence


def test_unknown_policy_is_not_a_fail() -> None:
    r = work_authorization_filter(
        job(description="Nothing about visas here."), profile(needs_sponsorship="yes")
    )
    assert r.decision == "unknown" and "Unknown, not assumed" in r.reason


def test_status() -> None:
    assert status_filter(job(status="closed")).decision == "fail"
    assert status_filter(job()).decision == "pass"


def test_combine() -> None:
    p, u, f = (FilterResult("a", d, "") for d in ("pass", "unknown", "fail"))
    assert combine([p, p]) == "pass" and combine([p, u]) == "unknown" and combine([u, f]) == "fail"
