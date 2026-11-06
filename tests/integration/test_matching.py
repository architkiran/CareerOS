import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from careeros.db.models import ActivityEvent, Job, JobLaneMatch, MatchOverride, Task
from careeros.modules.ingestion.service import run_all
from careeros.modules.matching import service as matching
from careeros.modules.profile import service as profile_service
from careeros.modules.profile.schemas import ProfileIn, SkillIn, WorkAuthorizationIn
from careeros.modules.scheduler.worker import Worker
from careeros.modules.sources import registry
from tests.conftest import post_form
from tests.helpers import ASHBY_URL, GH_URL, LEVER_URL, load_fixture, make_fetcher


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


@pytest.fixture
def world(factory: sessionmaker[Session]) -> sessionmaker[Session]:
    """Fixture jobs from all three ATS boards, default lanes, and a small verified profile."""
    with factory() as s:
        for t, tok, name in [
            ("greenhouse", "examplepay", "ExamplePay"),
            ("lever", "examplebank", "ExampleBank"),
            ("ashby", "examplecard", "ExampleCard"),
        ]:
            registry.add_source(s, registry.SourceIn(type=t, token=tok, name=name))  # type: ignore[arg-type]
        profile_service.add_default_lanes(s)
        profile_service.update_profile(
            s,
            ProfileIn(
                display_name="T",
                current_location="Boston, MA",
                open_to_relocation=True,
                salary_floor=80000,
            ),
        )
        profile_service.add_skill(s, SkillIn(name="SQL", verified_status="verified"))
        profile_service.add_skill(s, SkillIn(name="Python"))  # unverified: must not count
        s.commit()
    with respx.mock:
        respx.get(GH_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
        )
        respx.get(LEVER_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("lever_postings.json"))
        )
        respx.get(ASHBY_URL).mock(
            return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
        )
        run_all(factory, make_fetcher(max_attempts=1))
    return factory


def _job(f: sessionmaker[Session], title: str) -> Job:
    with f() as s:
        return s.scalars(select(Job).where(Job.title == title)).one()


def _count(f: sessionmaker[Session], model: type) -> int:
    with f() as s:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)


def test_scores_every_job_for_every_enabled_lane(world: sessionmaker[Session]) -> None:
    with world() as s:
        summary = matching.score_jobs(s)
        s.commit()
    assert summary.jobs == 7 and summary.scored == 7 * 6 and summary.unchanged == 0
    assert _count(world, JobLaneMatch) == 42
    with world() as s:
        assert s.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "job.scored")
        ).first()


def test_rescoring_unchanged_inputs_is_a_no_op(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        before = {
            (m.job_id, m.role_lane_id): (m.score, m.input_hash, m.created_at)
            for m in s.scalars(select(JobLaneMatch))
        }
    with world() as s:
        again = matching.score_jobs(s)
        s.commit()
        after = {
            (m.job_id, m.role_lane_id): (m.score, m.input_hash, m.created_at)
            for m in s.scalars(select(JobLaneMatch))
        }
    assert again.scored == 0 and again.unchanged == 42 and before == after


def test_expected_outcomes_on_fixture_jobs(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        best = matching.best_matches(s, [j.id for j in s.scalars(select(Job))])
    by_title = {_title(world, jid): v for jid, v in best.items()}
    assert by_title["Data Analyst"].lane_name == "Data / BI Analyst"
    assert by_title["Data Analyst"].match.classified
    assert by_title["Data Analyst"].effective_eligibility == "unknown"  # employment type not stated
    assert by_title["Senior Data Engineer"].effective_eligibility == "fail"
    assert by_title["Data Science Intern"].effective_eligibility == "fail"
    assert by_title["Financial Analyst (Contract)"].effective_eligibility == "fail"
    assert by_title["Business Operations Analyst"].effective_eligibility in ("pass", "unknown")


def _title(f: sessionmaker[Session], job_id: str) -> str:
    with f() as s:
        job = s.get(Job, job_id)
        assert job is not None
        return job.title


def test_verifying_a_skill_changes_scores(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
    analyst = _job(world, "Data Analyst")
    with world() as s:
        old = matching.matches_for_job(s, analyst.id)[0].match.score
        profile = profile_service.get_or_create_profile(s)
        python = next(x for x in profile_service.list_skills(s, profile.id) if x.name == "Python")
        profile_service.set_verified(s, "skills", python.skill_id, True)
        s.commit()
        summary = matching.score_jobs(s)
        s.commit()
        new = matching.matches_for_job(s, analyst.id)[0].match.score
    assert summary.scored > 0 and new > old


def test_confirmed_work_authorization_feeds_filters(world: sessionmaker[Session]) -> None:
    with world() as s:
        profile_service.save_work_authorization(
            s, WorkAuthorizationIn(requires_sponsorship_now="yes")
        )  # not confirmed yet
        assert matching.build_profile_input(s).needs_sponsorship == "unknown"
        profile_service.save_work_authorization(
            s, WorkAuthorizationIn(requires_sponsorship_now="yes", confirmed=True)
        )
        assert matching.build_profile_input(s).needs_sponsorship == "yes"


def test_disabling_lane_removes_its_matches(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        lane = profile_service.list_lanes(s)[0]
        profile_service.set_lane_enabled(s, lane.id, False)
        s.commit()
        matching.score_jobs(s)
        s.commit()
    assert _count(world, JobLaneMatch) == 7 * 5


def test_override_survives_rescoring_and_wins(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
    job = _job(world, "Senior Data Engineer")
    with world() as s:
        view = matching.matches_for_job(s, job.id)[0]
        assert view.effective_eligibility == "fail"
        matching.set_override(
            s,
            job.id,
            view.lane_id,
            eligibility="pass",
            score=88,
            reason="Team confirmed they hire juniors for this role",
        )
        s.commit()
        profile_service.add_skill(s, SkillIn(name="Spark", verified_status="verified"))
        s.commit()
        matching.score_jobs(s)
        s.commit()
        again = next(v for v in matching.matches_for_job(s, job.id) if v.lane_id == view.lane_id)
    assert (again.effective_eligibility, again.effective_score) == ("pass", 88)
    assert again.match.eligibility == "fail"  # computed result is still kept and shown


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({"eligibility": "pass", "score": None, "reason": " "}, "needs a reason"),
        ({"eligibility": "maybe", "score": None, "reason": "x"}, "pass or fail"),
        ({"eligibility": None, "score": 101, "reason": "x"}, "between 0 and 100"),
        ({"eligibility": None, "score": None, "reason": "x"}, "Choose"),
    ],
)
def test_override_validation(world: sessionmaker[Session], kw: dict, message: str) -> None:  # type: ignore[type-arg]
    job = _job(world, "Data Analyst")
    with world() as s:
        lane = profile_service.list_lanes(s)[0]
        with pytest.raises(matching.OverrideError, match=message):
            matching.set_override(s, job.id, lane.id, **kw)


def test_override_missing_job(world: sessionmaker[Session]) -> None:
    with world() as s:
        lane = profile_service.list_lanes(s)[0]
        with pytest.raises(LookupError):
            matching.set_override(s, "missing", lane.id, eligibility="pass", score=None, reason="x")


def test_match_counts(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        c = matching.match_counts(s)
    assert c.passing + c.needs_review + c.filtered_out + c.unscored == 7
    assert c.filtered_out >= 3


def test_worker_runs_rescoring_task(world: sessionmaker[Session]) -> None:
    from careeros.modules.scheduler.worker import enqueue_rescore

    with world() as s:
        enqueue_rescore(s, "test")
        s.commit()
    Worker(world).run_once()
    assert _count(world, JobLaneMatch) == 42


# ---------- web ----------


@pytest.fixture
def scored(world: sessionmaker[Session]) -> sessionmaker[Session]:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
    return world


def test_profile_change_queues_rescore(client: TestClient, factory: sessionmaker[Session]) -> None:
    post_form(client, "/profile/skills", {"name": "dbt"})
    with factory() as s:
        tasks = [t.task_type for t in s.scalars(select(Task))]
    assert tasks == ["match.all"]
    post_form(client, "/lanes/defaults")
    with factory() as s:
        assert [t.task_type for t in s.scalars(select(Task))] == ["match.all"]  # idempotent


def test_inbox_hides_filtered_out_by_default(
    scored: sessionmaker[Session], client: TestClient
) -> None:
    default = client.get("/jobs").text
    everything = client.get("/jobs?eligibility=any").text
    failing = client.get("/jobs?eligibility=fail").text
    assert default.count('data-testid="job-row"') + failing.count('data-testid="job-row"') == 7
    assert everything.count('data-testid="job-row"') == 7
    assert "Senior Data Engineer" not in default and "Senior Data Engineer" in failing


def test_inbox_lane_min_score_and_sort(scored: sessionmaker[Session], client: TestClient) -> None:
    with scored() as s:
        lane = next(x for x in profile_service.list_lanes(s) if x.name == "Data / BI Analyst")
    html = client.get(f"/jobs?lane_id={lane.id}&eligibility=any").text
    assert "<strong>Data Analyst</strong>" in html
    assert "<strong>Business Operations Analyst</strong>" not in html
    assert client.get("/jobs?eligibility=any&min_score=101").status_code == 200  # ignored
    assert (
        client.get("/jobs?eligibility=any&min_score=100").text.count('data-testid="job-row"') == 0
    )
    sorted_html = client.get("/jobs?eligibility=any&sort=score").text
    scores = [
        int(x.split("</strong>")[0])
        for x in sorted_html.split('<strong class="meter-num score">')[1:]
    ]
    assert scores == sorted(scores, reverse=True) and len(scores) >= 5


def test_inbox_match_column(scored: sessionmaker[Session], client: TestClient) -> None:
    html = client.get("/jobs?eligibility=any").text
    assert html.count('data-testid="match-cell"') == 7 and "pill-elig-" in html


def test_job_detail_shows_breakdown(scored: sessionmaker[Session], client: TestClient) -> None:
    job = _job(scored, "Data Analyst")
    html = client.get(f"/jobs/{job.id}").text
    assert html.count('data-testid="lane-match"') == 6
    assert 'data-testid="filters-table"' in html and 'data-testid="score-table"' in html
    assert "Skills alignment" in html and "match-v2" in html
    assert "Compensation" in html and "work authorization" in html
    assert "1 unverified skills were not counted." in html


def test_job_detail_unscored_state(app: FastAPI, client: TestClient) -> None:
    from careeros.db.models import Company

    with app.state.session_factory() as s:
        c = Company(canonical_name="C", normalized_name="c")
        s.add(c)
        s.flush()
        j = Job(
            canonical_url="https://x.test/1",
            company_id=c.id,
            title="T",
            normalized_title="t",
            description_hash="h",
            dedupe_key="k",
        )
        s.add(j)
        s.commit()
        jid = j.id
    assert 'data-testid="no-matches"' in client.get(f"/jobs/{jid}").text


def test_override_via_web(scored: sessionmaker[Session], client: TestClient) -> None:
    job = _job(scored, "Senior Data Engineer")
    with scored() as s:
        lane_id = matching.matches_for_job(s, job.id)[0].lane_id
    bad = post_form(client, f"/jobs/{job.id}/override", {"lane_id": lane_id, "eligibility": "pass"})
    assert bad.status_code == 422 and "needs a reason" in bad.text
    assert (
        post_form(
            client, f"/jobs/{job.id}/override", {"lane_id": lane_id, "score": "abc", "reason": "x"}
        ).status_code
        == 422
    )
    ok = post_form(
        client,
        f"/jobs/{job.id}/override",
        {"lane_id": lane_id, "eligibility": "pass", "reason": "Recruiter said juniors OK"},
    )
    assert ok.status_code == 303
    html = client.get(f"/jobs/{job.id}").text
    assert "Your override" in html and "Recruiter said juniors OK" in html
    assert "Senior Data Engineer" in client.get("/jobs").text  # no longer filtered out
    post_form(client, f"/jobs/{job.id}/override/clear", {"lane_id": lane_id})
    with scored() as s:
        assert s.scalars(select(MatchOverride)).all() == []
    assert (
        post_form(
            client,
            "/jobs/missing/override",
            {"lane_id": lane_id, "eligibility": "pass", "reason": "x"},
        ).status_code
        == 404
    )


def test_rescore_button(client: TestClient, factory: sessionmaker[Session]) -> None:
    assert post_form(client, "/matching/rescore").headers["location"] == "/?queued=1"
    assert post_form(client, "/matching/rescore").headers["location"] == "/?queued=already"


def test_overview_passing_stat(scored: sessionmaker[Session], client: TestClient) -> None:
    html = client.get("/partials/overview").text
    assert 'data-testid="stat-passing">' in html and "filtered out" in html


def test_stale_algorithm_version_triggers_rescore(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        assert not matching.has_stale_scores(s)
        for m in s.scalars(select(JobLaneMatch)):
            m.algorithm_version = "match-v0"
        s.commit()
        assert matching.has_stale_scores(s)
    w = Worker(world)
    w.ensure_current_scores()
    w.run_once()
    with world() as s:
        assert not matching.has_stale_scores(s)
        assert {m.algorithm_version for m in s.scalars(select(JobLaneMatch))} == {"match-v2"}


def test_greenhouse_full_time_from_description_can_pass(world: sessionmaker[Session]) -> None:
    with world() as s:
        job = s.scalars(select(Job).where(Job.title == "Data Analyst")).one()
        job.employment_type = None  # as if the board gave no metadata
        job.description_text += "\nThis is a full-time position."
        s.commit()
        matching.score_jobs(s)
        s.commit()
        view = next(
            v for v in matching.matches_for_job(s, job.id) if v.lane_name == "Data / BI Analyst"
        )
        emp = next(f for f in view.match.hard_filter_results_json if f["name"] == "employment_type")
    assert emp["decision"] == "pass" and "full-time" in emp["evidence"]


def test_batched_scoring_commits_in_chunks_and_matches_unbatched(
    world: sessionmaker[Session],
) -> None:
    from sqlalchemy import event

    commits: list[int] = []
    with world() as s:
        event.listen(s, "after_commit", lambda _s: commits.append(1))
        batched = matching.score_jobs(s, commit_every=2)
        s.commit()
        scores = {
            (m.job_id, m.role_lane_id): (m.score, m.eligibility)
            for m in s.scalars(select(JobLaneMatch))
        }
    assert len(commits) >= 4  # 7 jobs in batches of 2, plus the cleanup commit
    with world() as s:
        for m in s.scalars(select(JobLaneMatch)):
            m.algorithm_version = "old"
        s.commit()
        plain = matching.score_jobs(s)
        s.commit()
        again = {
            (m.job_id, m.role_lane_id): (m.score, m.eligibility)
            for m in s.scalars(select(JobLaneMatch))
        }
    assert again == scores and (batched.passing, batched.failing) == (plain.passing, plain.failing)


def test_contains_term_is_case_insensitive() -> None:
    from careeros.modules.matching.text import contains_term

    assert contains_term("We use POWER BI daily", "Power BI")
    assert contains_term("C++ and SQL", "c++") and not contains_term("PostgreSQL", "SQL")


def test_match_counts_reports_top_blocker(world: sessionmaker[Session], client: TestClient) -> None:
    with world() as s:
        matching.score_jobs(s)
        s.commit()
        c = matching.match_counts(s)
    if c.needs_review:
        assert c.top_blocker is not None and c.top_blocker[1] >= 1
        assert 'data-testid="top-blocker"' in client.get("/partials/overview").text
    else:
        assert c.top_blocker is None


def test_dashboard_sql_counts_match_inbox_with_overrides(world: sessionmaker[Session]) -> None:
    from careeros.modules.jobs.service import JobFilters, list_jobs, recent_jobs

    with world() as s:
        matching.score_jobs(s)
        s.commit()
        jobs = list(
            s.scalars(select(Job).where(Job.status == "active", Job.triage_status != "rejected"))
        )
        first = jobs[0]
        candidate = matching.matches_for_job(s, first.id)[0]
        matching.set_override(
            s, first.id, candidate.lane_id, eligibility="pass", score=99, reason="test review"
        )
        s.commit()
        views = matching.best_matches(s, [j.id for j in jobs])
        expected = {"pass": 0, "unknown": 0, "fail": 0, "unscored": 0}
        for job in jobs:
            view = views.get(job.id)
            key = view.effective_eligibility if view and view.match.classified else "unscored"
            expected[key] += 1
        counts = matching.match_counts(s)
        assert (counts.passing, counts.needs_review, counts.filtered_out, counts.unscored) == (
            expected["pass"],
            expected["unknown"],
            expected["fail"],
            expected["unscored"],
        )
        inbox, _ = list_jobs(s, JobFilters())
        bounded = recent_jobs(s, limit=2)
        assert [r.job.id for r in bounded] == [r.job.id for r in inbox[:2]]
        assert all(r.match is None or r.match.effective_eligibility != "fail" for r in bounded)


def test_dashboard_counts_when_every_lane_disabled(world: sessionmaker[Session]) -> None:
    with world() as s:
        matching.score_jobs(s)
        for lane in profile_service.list_lanes(s):
            lane.enabled = False
        s.commit()
        counts = matching.match_counts(s)
        assert counts.unscored == 7
        assert counts.passing == counts.needs_review == counts.filtered_out == 0
