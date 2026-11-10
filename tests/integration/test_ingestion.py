import copy
from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from careeros.db.models import ActivityEvent, Job, JobSourceRecord, Source, SourceRun
from careeros.modules.ingestion import service as ingest
from careeros.modules.sources import registry
from careeros.modules.sources.http import Fetcher
from tests.helpers import ASHBY_URL, GH_URL, LEVER_URL, load_fixture, make_fetcher


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


@pytest.fixture
def fetcher() -> Iterator[Fetcher]:
    f = make_fetcher(max_attempts=2)
    yield f
    f.close()


def _add(factory: sessionmaker[Session], type_: str, token: str, name: str) -> str:
    with factory() as s:
        src = registry.add_source(s, registry.SourceIn(type=type_, token=token, name=name))  # type: ignore[arg-type]
        s.commit()
        return src.id


def _count(factory: sessionmaker[Session], model: type) -> int:
    with factory() as s:
        return int(s.scalar(select(func.count()).select_from(model)) or 0)


def _jobs(factory: sessionmaker[Session]) -> list[Job]:
    with factory() as s:
        return list(s.scalars(select(Job).order_by(Job.title)))


@respx.mock
def test_first_run_ingests_and_reports(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    [result] = ingest.run_all(factory, fetcher)
    assert result.status == "partial"  # one malformed item
    assert (result.fetched, result.new, result.invalid) == (4, 3, 1)
    jobs = _jobs(factory)
    assert [j.title for j in jobs] == [
        "Data Analyst",
        "Data Science Intern",
        "Senior Data Engineer",
    ]
    analyst = jobs[0]
    assert analyst.canonical_url == "https://boards.greenhouse.io/examplepay/jobs/4012345"
    assert analyst.first_seen_at == analyst.last_seen_at
    assert analyst.status == "active"
    assert "<" not in analyst.description_text
    with factory() as s:
        rec = s.scalars(select(JobSourceRecord).where(JobSourceRecord.job_id == analyst.id)).one()
        assert rec.external_id == "4012345"
        assert rec.raw_json["content"].startswith("&lt;p&gt;")  # raw kept verbatim
        assert "gh_src" in rec.source_url  # original URL kept on the record
        run = s.scalars(select(SourceRun)).one()
        assert run.status == "partial" and run.error_summary and "item None" in run.error_summary


@respx.mock
def test_repeated_run_creates_no_duplicates(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    ingest.run_all(factory, fetcher)
    before = (_count(factory, Job), _count(factory, JobSourceRecord))
    [second] = ingest.run_all(factory, fetcher)
    assert (second.new, second.updated, second.duplicates) == (0, 0, 0)
    assert (_count(factory, Job), _count(factory, JobSourceRecord)) == before
    assert _count(factory, SourceRun) == 2


@respx.mock
def test_changed_posting_is_updated(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    data = load_fixture("lever_postings.json")
    route = respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=data))
    ingest.run_all(factory, fetcher)
    changed = copy.deepcopy(data)
    changed[0]["text"] = "Business Operations Analyst II"
    route.mock(return_value=httpx.Response(200, json=changed))
    [r] = ingest.run_all(factory, fetcher)
    assert r.updated == 1 and r.new == 0
    assert "Business Operations Analyst II" in [j.title for j in _jobs(factory)]
    assert _count(factory, Job) == 2


@respx.mock
def test_missing_job_closed_then_reopened(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    data = load_fixture("lever_postings.json")
    route = respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=data))
    ingest.run_all(factory, fetcher)
    route.mock(return_value=httpx.Response(200, json=data[:1]))
    [r] = ingest.run_all(factory, fetcher)
    assert r.closed == 1
    closed = [j for j in _jobs(factory) if j.status == "closed"]
    assert len(closed) == 1 and closed[0].closed_at is not None
    route.mock(return_value=httpx.Response(200, json=data))
    ingest.run_all(factory, fetcher)
    assert all(j.status == "active" and j.closed_at is None for j in _jobs(factory))


@respx.mock
def test_failed_fetch_does_not_close_jobs(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    route = respx.get(LEVER_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("lever_postings.json"))
    )
    ingest.run_all(factory, fetcher)
    route.mock(return_value=httpx.Response(500))
    [r] = ingest.run_all(factory, fetcher)
    assert r.status == "failed"
    assert all(j.status == "active" for j in _jobs(factory))


@respx.mock
def test_invalid_items_are_not_closed(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    data = load_fixture("lever_postings.json")
    route = respx.get(LEVER_URL).mock(return_value=httpx.Response(200, json=data))
    ingest.run_all(factory, fetcher)
    broken = copy.deepcopy(data)
    del broken[1]["hostedUrl"]  # still listed, but now unparseable
    route.mock(return_value=httpx.Response(200, json=broken))
    [r] = ingest.run_all(factory, fetcher)
    assert (r.status, r.invalid, r.closed) == ("partial", 1, 0)


@respx.mock
def test_same_url_from_two_sources_is_one_job(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "greenhouse", "examplepay2", "ExamplePay")
    gh = load_fixture("greenhouse_jobs.json")
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json=gh))
    mirror = copy.deepcopy(gh)
    for j in mirror["jobs"]:
        if "id" in j:
            j["id"] = j["id"] + 1_000_000  # different external ids, same URLs
    respx.get(GH_URL.replace("examplepay", "examplepay2")).mock(
        return_value=httpx.Response(200, json=mirror)
    )
    results = ingest.run_all(factory, fetcher)
    assert sorted(r.duplicates for r in results) == [0, 3]
    assert _count(factory, Job) == 3
    assert _count(factory, JobSourceRecord) == 6  # provenance kept for both sources


@respx.mock
def test_same_company_title_location_and_description_deduped(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "ashby", "examplecard", "ExampleCard")
    _add(factory, "lever", "examplecard", "ExampleCard")
    respx.get(ASHBY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
    )
    lever_copy = [
        {
            "id": "lever-1",
            "text": "Product Analyst",
            "hostedUrl": "https://jobs.lever.co/examplecard/lever-1",
            "categories": {"location": "San Francisco, CA", "commitment": "Full-time"},
            "descriptionPlain": "Analyze  product usage.",
        }
    ]
    respx.get("https://api.lever.co/v0/postings/examplecard").mock(
        return_value=httpx.Response(200, json=lever_copy)
    )
    results = {r.source_name + str(r.duplicates): r for r in ingest.run_all(factory, fetcher)}
    assert sum(r.duplicates for r in results.values()) == 1
    assert _count(factory, Job) == 2


@respx.mock
def test_same_title_different_description_flagged_possible_duplicate(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "ashby", "examplecard", "ExampleCard")
    _add(factory, "lever", "examplecard", "ExampleCard")
    respx.get(ASHBY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
    )
    respx.get("https://api.lever.co/v0/postings/examplecard").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "l2",
                    "text": "Product Analyst",
                    "hostedUrl": "https://jobs.lever.co/examplecard/l2",
                    "categories": {"location": "San Francisco, CA"},
                    "descriptionPlain": "A quite different description.",
                }
            ],
        )
    )
    ingest.run_all(factory, fetcher)
    flagged = [j for j in _jobs(factory) if j.possible_duplicate_of_id]
    assert len(flagged) == 1 and _count(factory, Job) == 3


@respx.mock
def test_one_failing_source_does_not_stop_others(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "lever", "examplebank", "ExampleBank")
    respx.get(GH_URL).mock(return_value=httpx.Response(404))
    respx.get(LEVER_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("lever_postings.json"))
    )
    results = {r.source_name: r for r in ingest.run_all(factory, fetcher)}
    assert results["ExamplePay"].status == "failed" and "404" in (results["ExamplePay"].error or "")
    assert results["ExampleBank"].status == "success" and results["ExampleBank"].new == 2
    with factory() as s:
        gh = s.scalars(select(Source).where(Source.board_token == "examplepay")).one()
        assert gh.last_error and gh.consecutive_failures == 1 and gh.enabled
        msgs = [
            e.message
            for e in s.scalars(
                select(ActivityEvent).where(ActivityEvent.event_type == "task.failed")
            )
        ]
        assert any("Check the board token" in m for m in msgs)


@respx.mock
def test_unexpected_exception_isolated(
    factory: sessionmaker[Session], fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "lever", "examplebank", "ExampleBank")
    respx.get(LEVER_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("lever_postings.json"))
    )
    from careeros.modules.sources.adapters import ADAPTERS

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(ADAPTERS["greenhouse"], "fetch_raw", boom)
    results = {r.source_name: r for r in ingest.run_all(factory, fetcher)}
    assert results["ExamplePay"].status == "failed" and "RuntimeError" in (
        results["ExamplePay"].error or ""
    )
    assert results["ExampleBank"].status == "success"


@respx.mock
def test_repeated_403_disables_source(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    route = respx.get(GH_URL).mock(return_value=httpx.Response(403))
    for _ in range(3):
        ingest.run_all(factory, fetcher)
    with factory() as s:
        src = s.scalars(select(Source)).one()
        assert src.enabled is False and "Disabled" in (src.last_error or "")
    assert route.call_count == 3  # 403 is never retried
    assert ingest.run_all(factory, fetcher) == []  # disabled sources are skipped


@respx.mock
def test_success_resets_failure_count(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "lever", "examplebank", "ExampleBank")
    route = respx.get(LEVER_URL).mock(return_value=httpx.Response(403))
    ingest.run_all(factory, fetcher)
    route.mock(return_value=httpx.Response(200, json=[]))
    ingest.run_all(factory, fetcher)
    with factory() as s:
        src = s.scalars(select(Source)).one()
        assert src.consecutive_failures == 0 and src.last_error is None and src.last_success_at


@respx.mock
def test_wrong_payload_shape_fails_cleanly(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
    [r] = ingest.run_all(factory, fetcher)
    assert r.status == "failed" and "Expected a list" in (r.error or "")


@respx.mock
def test_pipeline_events_recorded(factory: sessionmaker[Session], fetcher: Fetcher) -> None:
    _add(factory, "ashby", "examplecard", "ExampleCard")
    respx.get(ASHBY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("ashby_jobs.json"))
    )
    ingest.run_all(factory, fetcher)
    with factory() as s:
        types = [e.event_type for e in s.scalars(select(ActivityEvent).order_by(ActivityEvent.id))]
    assert types[0] == "source.added"
    assert "run.started" in types and types.count("job.ingested") == 2
    assert types[-1] == "source.fetch.completed"


def test_watchlist_sync_is_idempotent(factory: sessionmaker[Session], tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[source]]\ntype="lever"\ntoken="acme"\nname="Acme"\n'
        '[[source]]\ntype="ashby"\ntoken="beta"\nname="Beta"\nenabled=false\n'
    )
    entries = registry.load_watchlist(path)
    with factory() as s:
        assert registry.sync_watchlist(s, entries) == registry.SyncResult(2, 0)
        s.commit()
        assert registry.sync_watchlist(s, entries) == registry.SyncResult(0, 2, 0)
        assert [x.enabled for x in registry.list_sources(s)] == [True, False]


def test_watchlist_sync_disables_but_never_reenables(
    factory: sessionmaker[Session], tmp_path
) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[source]]\ntype="lever"\ntoken="plaid"\nname="Plaid"\n'
        '[[source]]\ntype="ashby"\ntoken="ramp"\nname="Ramp"\n'
    )
    with factory() as s:
        registry.sync_watchlist(s, registry.load_watchlist(path))
        ramp = next(x for x in registry.list_sources(s) if x.board_token == "ramp")
        registry.set_source_enabled(s, ramp.id, False)  # user disabled it in the dashboard
        s.commit()
        path.write_text(
            '[[source]]\ntype="lever"\ntoken="plaid"\nname="Plaid"\nenabled=false\n'
            '[[source]]\ntype="ashby"\ntoken="ramp"\nname="Ramp"\n'
        )
        result = registry.sync_watchlist(s, registry.load_watchlist(path))
        s.commit()
        assert result == registry.SyncResult(0, 2, 1)
        states = {x.board_token: x.enabled for x in registry.list_sources(s)}
        assert states == {"plaid": False, "ramp": False}  # ramp stays as the user left it
        assert registry.sync_watchlist(s, registry.load_watchlist(path)).disabled == 0


def test_watchlist_rejects_bad_entries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "sources.toml"
    path.write_text('[[source]]\ntype="linkedin"\ntoken="x"\nname="X"\n')
    with pytest.raises(ValueError):
        registry.load_watchlist(path)
    path.write_text('[[source]]\ntype="lever"\ntoken="../etc"\nname="X"\n')
    with pytest.raises(ValueError):
        registry.load_watchlist(path)


def test_duplicate_source_rejected(factory: sessionmaker[Session]) -> None:
    _add(factory, "lever", "acme", "Acme")
    with factory() as s, pytest.raises(registry.DuplicateSourceError):
        registry.add_source(s, registry.SourceIn(type="lever", token="acme", name="Acme again"))


def _hosted_board(n: int) -> dict:  # type: ignore[type-arg]
    """A company-hosted Greenhouse board: every URL differs only by gh_jid."""
    return {
        "jobs": [
            {
                "id": 5_000_000 + i,
                "title": f"Role {i}",
                "absolute_url": f"https://examplepay.com/jobs/search?gh_jid={5_000_000 + i}",
                "location": {"name": "New York, NY"},
                "content": f"<p>Role {i}</p>",
            }
            for i in range(n)
        ]
    }


@respx.mock
def test_company_hosted_urls_are_separate_jobs(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json=_hosted_board(25)))
    [r] = ingest.run_all(factory, fetcher)
    assert (r.fetched, r.new, r.duplicates) == (25, 25, 0)
    assert _count(factory, Job) == 25


@respx.mock
def test_same_board_never_merges_its_own_postings(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    """Even identical URL, title, location and text from one board stay separate jobs."""
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    twin = {
        "title": "Data Analyst",
        "absolute_url": "https://examplepay.com/careers",
        "location": {"name": "NYC"},
        "content": "<p>Same</p>",
    }
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json={"jobs": [twin | {"id": 1}, twin | {"id": 2}]})
    )
    [r] = ingest.run_all(factory, fetcher)
    assert (r.new, r.duplicates) == (2, 0)
    flagged = [j for j in _jobs(factory) if j.possible_duplicate_of_id]
    assert len(flagged) == 1  # surfaced for review instead of silently merged


@respx.mock
def test_cross_source_url_duplicate_still_merges(
    factory: sessionmaker[Session], fetcher: Fetcher
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    _add(factory, "greenhouse", "examplepay2", "ExamplePay")
    respx.get(GH_URL).mock(return_value=httpx.Response(200, json=_hosted_board(3)))
    mirror = _hosted_board(3)
    for j in mirror["jobs"]:
        j["id"] += 1  # different ids, same URLs on a second board
    respx.get(GH_URL.replace("examplepay", "examplepay2")).mock(
        return_value=httpx.Response(200, json=mirror)
    )
    results = ingest.run_all(factory, fetcher)
    assert sorted(r.duplicates for r in results) == [0, 3]
    assert _count(factory, Job) == 3


@respx.mock
def test_parser_upgrade_renormalises_stored_jobs(
    factory: sessionmaker[Session], fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add(factory, "greenhouse", "examplepay", "ExamplePay")
    respx.get(GH_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse_jobs.json"))
    )
    ingest.run_all(factory, fetcher)
    with factory() as s:
        job = s.scalars(select(Job).where(Job.title == "Data Analyst")).one()
        job.employment_type = None  # as stored by an older parser
        s.commit()
    [same] = ingest.run_all(factory, fetcher)
    assert same.updated == 0  # same payload, same parser: nothing to do
    monkeypatch.setattr(ingest, "NORMALIZER_VERSION", "test-next")
    [upgraded] = ingest.run_all(factory, fetcher)
    assert (
        upgraded.updated == 1 and upgraded.new == 0
    )  # only the changed employment field is material
    with factory() as s:
        assert (
            s.scalars(select(Job).where(Job.title == "Data Analyst")).one().employment_type
            == "full_time"
        )
