from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from careeros.common.clock import utcnow
from careeros.db.models import AgentRun, Application, Approval, Document, Job, SourceRun
from careeros.modules.agents import support
from careeros.modules.applications.service import start_application
from careeros.modules.documents import service as documents
from careeros.modules.documents.workbench import Choices
from careeros.modules.jobs.service import JobFilters, list_jobs
from careeros.modules.resumes.master import import_user_master
from careeros.modules.scheduler.worker import Worker
from careeros.modules.sources.monitoring import coverage, tick
from careeros.modules.sources.registry import SourceIn, add_source
from careeros.modules.system.settings_store import set_setting
from tests.conftest import post_form
from tests.integration.test_documents import _setup
from tests.unit.test_master_resume import MASTER


def setup_workbench(app):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    root = Path(app.state.settings.data_dir)
    source = root / "master.tex"
    source.write_text(MASTER)
    with app.state.session_factory() as s:
        import_user_master(s, source, confirm_user_authored=True)
        a = start_application(s, job_id)
        s.commit()
        return a.id


def test_editor_keeps_master_evidence_and_saves_a_version_without_changing_profile(
    app, client, pdf_compiler
):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    with app.state.session_factory() as s:
        c = documents.load_candidate(s)
        chosen = Choices(
            project_refs=[p.ref for p in c.projects],
            experience_refs=[e.ref for e in c.experience],
            skills=[x.text for x in c.skills],
            summary="Data analyst building SQL reports.",
            experience_edits={e.ref: e.text.split("|", 2)[-1] for e in c.experience},
            feedback="Keep every experience.",
        )
        d = documents.generate(
            s,
            app_id,
            "resume",
            Path(app.state.settings.data_dir),
            render_format="pdf",
            choices=chosen,
        )
        s.commit()
        text = documents.load_content(d).as_text()
        assert "30%" in text and "20 teams" in text
        assert "Keep every experience" not in text
        assert "choices" in documents.load_content(d).context
        assert documents.load_candidate(s) == c
    page = client.get(f"/applications/{app_id}/workbench")
    assert page.status_code == 200 and "Requirements &amp; evidence" in page.text
    assert "Generate revised PDF" in page.text and "30%" in page.text
    assert client.post(f"/applications/{app_id}/workbench").status_code == 403


def test_feedback_is_saved_without_compilation_and_unverified_edits_are_rejected(app, client):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    with app.state.session_factory() as s:
        c = documents.load_candidate(s)
    values = {
        "projects": [p.ref for p in c.projects],
        "experiences": [e.ref for e in c.experience],
        "skills": [x.text for x in c.skills],
        "summary": "Data analyst building SQL reports.",
        "base_version": "0",
        "feedback": "Keep the original bullets.",
        "intent": "feedback",
        **{"edit-" + e.ref: e.text.split("|", 2)[-1] for e in c.experience},
    }
    response = post_form(client, f"/applications/{app_id}/workbench", values)
    assert response.status_code == 200 and "Feedback saved" in response.text
    assert (Path(app.state.settings.data_dir) / "documents" / app_id / "feedback.json").is_file()
    bad = post_form(
        client,
        f"/applications/{app_id}/workbench",
        {**values, "intent": "generate", "summary": "Built a Rust platform for 999 customers."},
    )
    assert bad.status_code == 422 and "unverified detail" in bad.text
    with app.state.session_factory() as s:
        assert s.scalars(select(Document)).all() == []


def test_publication_filter_does_not_confuse_discovery_unknown_or_future_dates(app):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as s:
        job = s.get(Job, job_id)
        for posted, expected in [
            (None, 0),
            (utcnow() - timedelta(days=5), 0),
            (utcnow() + timedelta(hours=1), 0),
            (utcnow() - timedelta(minutes=10), 1),
        ]:
            job.posted_at = posted
            s.flush()
            _, total = list_jobs(s, JobFilters(published_minutes=60))
            assert total == expected


def test_monitor_enforces_provider_cadence_and_deduplicates_scheduled_work(app):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as s:
        source = add_source(
            s,
            SourceIn(type="remotive", token="public", name="Remotive", refresh_interval_minutes=15),
        )
        s.add(
            SourceRun(
                source_id=source.id,
                started_at=utcnow() - timedelta(minutes=1),
                finished_at=utcnow(),
                status="success",
            )
        )
        s.commit()
        row = coverage(s)[0]
        assert row.minutes == 360 and row.next_due > utcnow()
        set_setting(s, "watch.enabled", True)
        tick(s)
        s.commit()
        assert s.scalars(select(AgentRun)).all() == []
        source2 = add_source(s, SourceIn(type="greenhouse", token="due", name="Due"))
        set_setting(s, "watch.last_tick", (utcnow() - timedelta(minutes=2)).isoformat())
        tick(s)
        tick(s)
        s.commit()
        runs = s.scalars(select(AgentRun)).all()
        assert len(runs) == 1 and runs[0].agent_key == "freshness"
        assert source2.id


def test_starting_application_queues_real_evidence_and_networking_agents(app, client):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    response = post_form(client, f"/jobs/{job_id}/application")
    app_id = response.headers["location"].rsplit("/", 1)[-1]
    worker = Worker(app.state.session_factory, data_dir=Path(app.state.settings.data_dir))
    assert worker.run_once() and worker.run_once()
    with app.state.session_factory() as s:
        runs = s.scalars(select(AgentRun)).all()
        assert {r.agent_key for r in runs} == {"evidence", "networking"}
        assert all(r.status == "succeeded" for r in runs)
        assert s.scalars(select(Approval)).all() == []
        assert s.get(Application, app_id).status == "preparing"
    brief = support.load_report(Path(app.state.settings.data_dir), app_id, "networking")
    assert brief["leads"] == [] and "[Name]" in brief["email_draft"]
    assert "Recon" in brief["email_draft"]


def test_networking_extracts_published_recruiting_lead_but_not_support_or_guessed_email(app):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as s:
        a = start_application(s, job_id)
        job = s.get(Job, job_id)
        job.description_text = "Recruiting contact: talent@acme.example. Questions about hiring."
        report = support.networking(s, a.id)
        assert report["leads"][0]["email"] == "talent@acme.example"
        assert report["leads"][0]["source"] == job.canonical_url
        job.description_text = "For recruitment accommodations, contact support@acme.example."
        assert support.networking(s, a.id)["leads"] == []


def test_verified_edit_punctuation_is_not_a_new_fact():
    from careeros.modules.documents.workbench import validate_edit

    validate_edit("Working with SQL, Python, Tableau.", "SQL Python Tableau")


def test_generated_preview_is_a_private_png_and_rejects_tampered_pdf(app, client, pdf_compiler):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    with app.state.session_factory() as s:
        d = documents.generate(
            s, app_id, "resume", Path(app.state.settings.data_dir), render_format="pdf"
        )
        s.commit()
    response = client.get(f"/documents/{d.id}/preview")
    assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
    assert response.headers["cache-control"] == "no-store"
    Path(d.storage_path).write_bytes(b"tampered")
    assert client.get(f"/documents/{d.id}/preview").status_code == 409


def test_pinned_project_outside_automatic_shortlist_is_not_discarded(app, pdf_compiler):  # type: ignore[no-untyped-def]
    from careeros.modules.profile import service as profiles
    from careeros.modules.profile.schemas import ProjectIn

    app_id = setup_workbench(app)
    with app.state.session_factory() as s:
        for i in range(6):
            profiles.add_project(
                s,
                ProjectIn(
                    name=f"Extra project {i}",
                    description="Verified work",
                    verified_status="verified",
                ),
            )
        candidate = documents.load_candidate(s)
        pinned = next(p for p in candidate.projects if p.text.startswith("Extra project 5|"))
        choices = Choices(
            project_refs=[pinned.ref],
            experience_refs=[e.ref for e in candidate.experience],
            skills=[x.text for x in candidate.skills],
        )
        doc = documents.generate(
            s,
            app_id,
            "resume",
            Path(app.state.settings.data_dir),
            render_format="pdf",
            choices=choices,
        )
        projects = dict(documents.load_content(doc).sections)["Projects"]
        assert projects and all(p.refs == [pinned.ref] for p in projects)
