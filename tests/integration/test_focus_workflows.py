import json

from sqlalchemy import select

from careeros.db.models import Job, Source
from careeros.modules.applications.service import start_application
from careeros.modules.documents import service as docs
from careeros.modules.profile import service as profiles
from careeros.modules.profile.schemas import ProjectIn
from tests.conftest import post_form
from tests.integration.test_documents import _setup


def test_tailoring_selects_different_verified_evidence_for_different_jobs(app, pdf_compiler):  # type: ignore[no-untyped-def]
    factory = app.state.session_factory
    first = _setup(factory)
    with factory() as s:
        profiles.add_project(
            s,
            ProjectIn(
                name="Streaming Platform",
                description="Kafka event streaming with PySpark",
                technologies=["Kafka", "PySpark"],
                verified_status="verified",
            ),
        )
        profiles.add_project(
            s,
            ProjectIn(
                name="Reporting Dashboard",
                description="SQL Tableau financial reporting",
                technologies=["SQL", "Tableau"],
                verified_status="verified",
            ),
        )
        a = s.get(Job, first)
        a.description_text = "SQL and Tableau reporting dashboards"
        b = Job(
            company_id=a.company_id,
            title="Data Engineer",
            normalized_title="data engineer",
            description_text="Kafka PySpark event streaming and pipelines",
            description_hash="de",
            canonical_url="https://acme.example/de",
            dedupe_key="de",
        )
        s.add(b)
        s.flush()
        reports = []
        for job in (a, b):
            application = start_application(s, job.id)
            document = docs.generate(
                s,
                application.id,
                "resume",
                app.state.settings.data_dir,
                render_format="pdf",
                project_limit=2,
            )
            content = docs.load_content(document)
            reports.append(json.loads(content.context["tailoring"]))
            assert "Rust" not in content.as_text()
            assert document.storage_path.endswith(".pdf")
        assert reports[0]["selected_projects"][0] == "Reporting Dashboard"
        assert reports[1]["selected_projects"][0] == "Streaming Platform"
        assert reports[0]["matched_verified_skills"] == ["SQL"]
        assert "Kafka" not in reports[1]["matched_verified_skills"]  # not a verified skill row


def test_every_visible_resume_generation_action_produces_pdf(app, client, pdf_compiler):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as s:
        application = start_application(s, job_id)
        s.commit()
    response = post_form(
        client, f"/applications/{application.id}/documents", {"document_type": "resume"}
    )
    assert response.status_code == 303
    with app.state.session_factory() as s:
        document = docs.latest(s, application.id, "resume")
        assert document.storage_path.endswith(".pdf")
    response = client.get(f"/documents/{document.id}/download")
    assert response.headers["content-type"] == "application/pdf"
    assert "Archit_Kiran_Kumar_Resume.pdf" in response.headers["content-disposition"]
    page = client.get(f"/applications/{application.id}")
    assert "What changed for this role" in page.text and "Download tailored PDF" in page.text
    assert "Generate resume</button>" not in page.text
    assert (
        client.get(f"/documents/{document.id}/download?inline=true").headers["x-frame-options"]
        == "SAMEORIGIN"
    )


def test_manual_import_is_user_assisted_idempotent_and_cannot_scrape(session, client, monkeypatch):  # type: ignore[no-untyped-def]
    from careeros.modules.sources.http import Fetcher

    def forbidden(*args, **kwargs):
        raise AssertionError("No remote fetch is allowed")

    monkeypatch.setattr(Fetcher, "get_json", forbidden)
    data = {
        "title": "Data Analyst",
        "company": "Example Manufacturing",
        "url": "https://www.linkedin.com/jobs/view/12345",
        "description": "SQL and Python reporting across manufacturing operations.",
        "confirmed": "on",
    }
    assert client.post("/opportunities/import", data=data).status_code == 403
    result = post_form(client, "/opportunities/import", data)
    assert result.status_code == 303
    assert (
        post_form(client, "/opportunities/import", data).headers["location"]
        == result.headers["location"]
    )
    assert len(session.scalars(select(Job)).all()) == 1
    source = session.scalars(select(Source)).one()
    assert source.enabled is False and source.source_type == "manual"
    assert (
        post_form(
            client, "/opportunities/import", {**data, "url": "file:///etc/passwd"}
        ).status_code
        == 422
    )
    assert post_form(client, "/opportunities/import", {**data, "confirmed": ""}).status_code == 422


def test_primary_navigation_and_jobs_split_view(app, client):  # type: ignore[no-untyped-def]
    _setup(app.state.session_factory)
    page = client.get("/mission-control").text
    nav = page.split('data-testid="workspace-nav"')[1].split("</nav>")[0]
    assert nav.count("<a ") == 3
    assert "Your next steps" in page and "Latest career review</h2>" not in page
    jobs = client.get("/jobs").text
    assert 'aria-label="Selected opportunity"' in jobs and 'class="job-list"' in jobs
    assert "<thead>" not in jobs


def test_editing_notes_are_omitted_without_losing_verified_sentence():
    from careeros.modules.documents.content import experience_paragraphs, internal_note

    text = "SQL/Python analysis, Power BI reporting. Confirm exact title and dates."
    assert internal_note(text)
    assert experience_paragraphs(text) == ["SQL/Python analysis, Power BI reporting."]


def test_background_matching_is_visible_in_activity_and_today(app, client):  # type: ignore[no-untyped-def]
    from careeros.modules.scheduler.worker import enqueue_rescore

    with app.state.session_factory() as s:
        task, _ = enqueue_rescore(s, "profile updated")
        task.status = "running"
        s.commit()
    assert "Refreshing saved job scores" in client.get("/agents").text
    today = client.get("/mission-control").text
    assert "Refreshing job scores" in today and "Ready when you are" not in today


def test_public_board_attribution_is_visible_on_today_and_opportunities(app, client):  # type: ignore[no-untyped-def]
    from careeros.db.models import JobSourceRecord
    from careeros.modules.matching.service import score_jobs
    from careeros.modules.sources.registry import SourceIn, add_source

    job_id = _setup(app.state.session_factory)
    original = "https://jobicy.com/jobs/123-analyst"
    from careeros.common.clock import utcnow
    from careeros.db.models import Job

    with app.state.session_factory() as s:
        s.get(Job, job_id).posted_at = utcnow()
        s.get(Job, job_id).publication_kind = "provider_reported"
        source = add_source(s, SourceIn(type="jobicy", token="usa", name="Jobicy"))
        s.add(
            JobSourceRecord(
                job_id=job_id,
                source_id=source.id,
                external_id="123",
                source_url=original,
                raw_json={},
                raw_hash="x",
            )
        )
        profiles.add_default_lanes(s)
        score_jobs(s)
        s.commit()
    today = client.get("/mission-control").text
    primary = today.split("<h2>Fresh openings</h2>")[1].split("New to your feed")[0]
    assert original not in primary  # Board publication is not employer publication.
    for path in ("/mission-control", "/jobs?view=recommended&sort=score"):
        page = client.get(path).text
        assert original in page and "Source: Jobicy" in page
