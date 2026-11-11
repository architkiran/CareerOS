"""Mission spec 19.1: every eligibility case has an explicit expected verdict."""

from datetime import UTC, datetime, timedelta

import pytest

from careeros.modules.eligibility.engine import CandidateRules, JobFacts, classify_role, evaluate
from careeros.modules.sponsorship.levels import LcaSummary, assess

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)
RULES = CandidateRules(
    needs_sponsorship=True, open_to_relocation=True, verified_skills=("SQL", "Python", "Power BI")
)
LCA = LcaSummary("exact", ("ACME FINANCIAL INC",), (2026,), 42, 17, ("Data Analyst",), "LCA.xlsx")
ENTRY = "This is a full-time role for recent graduates. 0-1 years of experience with SQL."


def run(
    title="Data Analyst",
    description=ENTRY,
    location="Boston, MA",
    lca=None,
    feed_flag=None,
    rules=RULES,
    **facts,
):
    base = {
        "workplace_type": None,
        "employment_type": None,
        "status": "active",
        "last_seen_at": NOW - timedelta(hours=3),
        "posted_at": NOW - timedelta(days=2),
        "first_seen_at": NOW - timedelta(days=1),
        "has_official_source": True,
    }
    base.update(facts)
    job = JobFacts(
        title=title,
        company="Acme Financial",
        location_text=location,
        description=description,
        **base,
    )
    sponsorship = assess(
        description=description,
        posting_url="https://example.com/job/1",
        posting_is_official=base["has_official_source"],
        observed_at="2026-11-11",
        feed_flag=feed_flag,
        lca=lca,
    )
    return evaluate(job, rules, sponsorship, NOW), sponsorship


def check(result, key):
    return next(c for c in result.checks if c.key == key)


def test_explicit_role_level_sponsorship_is_eligible_level_a():
    result, s = run(description=ENTRY + " Visa sponsorship is available for this position.")
    assert (result.verdict, s.level) == ("eligible", "A")
    assert s.items[0].quote and "sponsorship is available" in s.items[0].quote.lower()


def test_employer_lca_history_without_role_confirmation_is_eligible_level_b():
    result, s = run(lca=LCA)
    assert (result.verdict, s.level) == ("eligible", "B")
    assert "unconfirmed" in s.label.lower() and "Ask the recruiter" in result.next_action
    assert s.recruiter_question


def test_explicit_no_sponsorship_is_rejected_level_d_even_with_lca_history():
    result, s = run(description=ENTRY + " We are unable to sponsor visas for this role.", lca=LCA)
    assert (result.verdict, s.level) == ("rejected", "D")
    assert result.reason.startswith("Sponsorship pathway") and s.contradictions


@pytest.mark.parametrize(
    "wording",
    [
        "Must be a U.S. citizen.",
        "Applicants must be US citizens or permanent residents.",
        "Requires an active Secret security clearance.",
        "Candidates must have permanent work authorization in the United States.",
        "Must be authorized to work in the US without sponsorship now or in the future.",
        "This position is not eligible for visa sponsorship.",
        "We do not offer immigration sponsorship for this position.",
        "We are not able to hire candidates on OPT or CPT.",
    ],
)
def test_citizenship_or_permanent_authorization_requirements_are_rejected(wording):
    result, s = run(description=ENTRY + " " + wording)
    assert (result.verdict, s.level) == ("rejected", "D"), wording


def test_three_to_five_years_required_is_rejected():
    result, _ = run(description="Requirements: 3-5 years of experience in analytics. SQL.")
    assert result.verdict == "rejected" and "3+ years" in result.reason


@pytest.mark.parametrize(
    "title", ["Data Analyst Intern", "Data Analyst (Part-Time)", "Contract Business Analyst"]
)
def test_internship_part_time_and_contract_are_rejected(title):
    result, _ = run(title=title)
    assert result.verdict == "rejected" and result.reason.startswith("Full-time employment")


def test_source_stated_part_time_is_rejected():
    assert run(employment_type="part_time")[0].verdict == "rejected"


def test_international_role_is_rejected():
    result, _ = run(location="London, UK")
    assert result.verdict == "rejected" and result.reason.startswith("US work location")


def test_us_remote_restricted_to_listed_states_needs_review():
    text = ENTRY + " This is a remote role. You must reside in Texas, Florida, Georgia."
    result, _ = run(description=text, location="Remote - United States", lca=LCA)
    assert result.verdict == "review" and check(result, "geography").decision == "unknown"


def test_closed_job_is_rejected_and_stale_job_needs_review():
    assert run(status="closed")[0].verdict == "rejected"
    stale, _ = run(lca=LCA, last_seen_at=NOW - timedelta(days=9))
    assert stale.verdict == "review" and check(stale, "open").decision == "unknown"


def test_missing_sponsorship_information_goes_to_research_queue_not_eligible():
    result, s = run()
    assert (result.verdict, s.level) == ("research", "U")
    assert "unverified" in result.next_action.lower()


def test_ambiguous_work_authorization_wording_is_flagged_not_passed():
    result, s = run(description=ENTRY + " Applicants must be authorized to work in the US.")
    assert s.level == "U" and s.ambiguous_wording and result.verdict == "research"


def test_third_party_sponsorship_tag_is_level_c_only():
    result, s = run(feed_flag="Offers Sponsorship")
    assert (result.verdict, s.level) == ("research", "C")
    negative, s2 = run(feed_flag="Does Not Offer Sponsorship", lca=LCA)
    assert s2.level == "B" and s2.contradictions and negative.flags


def test_possible_entity_match_never_exceeds_level_c():
    possible = LcaSummary("possible", ("ACME FINANCIAL BANK AND TRUST",), (2026,), 9, 3)
    result, s = run(lca=possible)
    assert (result.verdict, s.level) == ("research", "C")


def test_analyst_title_alone_is_not_proof_of_entry_level():
    result, _ = run(description="Join our team. Strong SQL and communication skills.", lca=LCA)
    assert result.verdict == "review" and check(result, "stage").decision == "unknown"


def test_senior_and_manager_titles_are_rejected_but_apm_is_not():
    assert run(title="Senior Data Analyst")[0].verdict == "rejected"
    assert run(title="Analytics Manager")[0].verdict == "rejected"
    assert run(title="Associate Product Manager", lca=LCA)[0].verdict == "eligible"


def test_out_of_scope_role_is_rejected_and_generic_analyst_is_reviewed():
    assert run(title="Software Engineer")[0].verdict == "rejected"
    generic, _ = run(title="GIS Analyst", lca=LCA)
    assert generic.verdict == "review" and check(generic, "role").decision == "unknown"


def test_unconfirmed_candidate_sponsorship_need_blocks_eligibility():
    result, _ = run(lca=LCA, rules=CandidateRules(needs_sponsorship=None))
    assert result.verdict == "research" and check(result, "authorization").decision == "unknown"


def test_unstated_employment_type_is_shown_as_an_assumption():
    result, _ = run(description="Recent graduates welcome. 0-1 years of experience.", lca=LCA)
    assert check(result, "employment").decision == "assumed" and result.verdict == "eligible"


def test_fixed_term_wording_is_flagged():
    result, _ = run(description=ENTRY + " This is a 12-month contract.", lca=LCA)
    assert any("Fixed-term" in f for f in result.flags)


def test_ranking_never_overrides_a_hard_failure():
    text = "Senior role. SQL Python Power BI. Visa sponsorship is available."
    result, _ = run(title="Senior Data Analyst", description=text, lca=LCA)
    assert result.verdict == "rejected" and result.fit is None


def test_level_a_outranks_level_b_for_the_same_role():
    a, _ = run(description=ENTRY + " We will sponsor work visas.")
    b, _ = run(lca=LCA)
    assert a.rank > b.rank


@pytest.mark.parametrize(
    ("title", "family"),
    [
        ("Technical Business Analyst", "tech_systems"),
        ("Junior Data Engineer", "data_engineering"),
        ("FP&A Analyst", "finance_risk"),
        ("Business Intelligence Analyst", "data_bi"),
        ("Strategy Analyst", "business_strategy"),
        ("Product Operations Associate", "product"),
        ("Forklift Operator", None),
    ],
)
def test_role_family_classification(title, family):
    assert classify_role(title)[0] == family
