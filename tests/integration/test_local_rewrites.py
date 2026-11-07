"""Exercise proposed rewrites through durable work, review and PDF revision boundaries."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from careeros.db.models import Application, Document, Job, Mission, Task
from careeros.modules.documents import rewriter
from careeros.modules.documents import service as documents
from careeros.modules.documents.content import experience_paragraphs
from careeros.modules.documents.workbench import validate_edit
from careeros.modules.models.gateway import ModelGateway
from careeros.modules.scheduler.worker import Worker
from tests.conftest import post_form
from tests.integration.test_evidence_workbench import setup_workbench
from tests.integration.test_gateway import FakeProvider


def reply(app, app_id):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        c = documents.load_candidate(session)
        return {
            "summary": "Data analyst building SQL reports and Python analytics.",
            "experience": [
                {"ref": e.ref, "bullets": experience_paragraphs(e.text.split("|", 2)[-1])}
                for e in c.experience
            ],
            "project_refs": [p.ref for p in c.projects],
            "skills": [s.text for s in c.skills],
            "rationale": "Selected verified analytics evidence.",
        }


def inject(monkeypatch, value):  # type: ignore[no-untyped-def]
    provider = FakeProvider([json.dumps(value)])
    monkeypatch.setattr(
        rewriter, "ModelGateway", lambda settings: ModelGateway(settings, provider=provider)
    )
    return provider


def test_rewrite_is_private_reviewable_and_never_auto_generates(app, client, monkeypatch):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    value = reply(app, app_id)
    inject(monkeypatch, value)
    root = Path(app.state.settings.data_dir)
    with app.state.session_factory() as session:
        original = documents.load_candidate(session)
        report = rewriter.propose(session, app_id, root, app.state.settings, "Emphasize SQL")
        session.commit()
        assert documents.load_candidate(session) == original
        assert not session.scalars(select(Document)).all()
    path = root / "documents" / app_id / "rewrite-proposal.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert set(report["choices"]["experience_refs"]) == {e.ref for e in original.experience}
    page = client.get(f"/applications/{app_id}/workbench")
    assert "<title>Tailoring workbench · CareerOS</title>" in page.text
    assert "Review proposed changes" in page.text and "Master evidence" in page.text
    assert client.post(f"/applications/{app_id}/rewrite/review").status_code == 403
    response = post_form(
        client, f"/applications/{app_id}/rewrite/review", {"proposal": report["created_at"]}
    )
    assert response.status_code == 303
    assert "Proposed edits loaded below" in client.get(response.headers["location"]).text
    with app.state.session_factory() as session:
        assert not session.scalars(select(Document)).all()
        job = session.get(Job, session.get(Application, app_id).job_id)
        job.description_hash = "changed"
        session.commit()
    assert (
        post_form(
            client, f"/applications/{app_id}/rewrite/review", {"proposal": report["created_at"]}
        ).status_code
        == 409
    )
    assert "Profile or posting changed" in client.get(f"/applications/{app_id}/workbench").text


def test_rewrite_cannot_drop_experience(app, monkeypatch):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    value = reply(app, app_id)
    value["experience"] = []
    # Use one valid role from a multiple-role master to pass shape validation but
    # fail the stronger source completeness requirement.
    original = reply(app, app_id)["experience"]
    assert len(original) > 1
    value["experience"] = original[:1]
    inject(monkeypatch, value)
    with app.state.session_factory() as session, pytest.raises(ValueError, match="omitted"):
        rewriter.propose(session, app_id, Path(app.state.settings.data_dir), app.state.settings)
    assert not rewriter.load(Path(app.state.settings.data_dir), app_id)


def test_bad_role_rewrite_preserves_original_with_visible_warning(app, monkeypatch):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    value = reply(app, app_id)
    first = value["experience"][0]
    original = list(first["bullets"])
    first["bullets"] = ["Built Rust reports for 999 banks."]
    provider = FakeProvider([json.dumps(value), "invalid"])
    monkeypatch.setattr(
        rewriter, "ModelGateway", lambda settings: ModelGateway(settings, provider=provider)
    )
    with app.state.session_factory() as session:
        report = rewriter.propose(
            session, app_id, Path(app.state.settings.data_dir), app.state.settings
        )
        assert report["warnings"]
        assert report["choices"]["experience_edits"][first["ref"]] == "\n".join(original)


def test_durable_rewrite_uses_private_instructions_and_deduplicates(app, client, monkeypatch):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    assert post_form(client, f"/applications/{app_id}/rewrite").status_code == 409
    app.state.settings.model_provider = "llama_cpp"
    provider = inject(monkeypatch, reply(app, app_id))
    monkeypatch.setattr("careeros.config.get_settings", lambda: app.state.settings)
    url = f"/applications/{app_id}/rewrite"
    assert client.get(url + "/status").json() == {"status": "idle"}
    assert post_form(client, url, {"feedback": "Emphasize SQL"}).status_code == 303
    assert client.get(url + "/status").json() == {"status": "queued"}
    assert (
        post_form(client, url, {"feedback": "Should not overwrite active work"}).status_code == 303
    )
    with app.state.session_factory() as session:
        missions = list(
            session.scalars(select(Mission).where(Mission.workflow == "tailoring:" + app_id))
        )
        assert len(missions) == 1
        task = session.scalars(select(Task).where(Task.task_type == "agent.execute")).one()
        assert "Emphasize" not in json.dumps(task.payload_json)
    assert Worker(app.state.session_factory, data_dir=Path(app.state.settings.data_dir)).run_once()
    assert "Emphasize SQL" in provider.prompts[0]
    assert "Should not overwrite" not in provider.prompts[0]
    with app.state.session_factory() as session:
        mission = session.get(Mission, missions[0].id)
        assert mission.status == "succeeded"
        assert not session.scalars(select(Document)).all()
    assert "Review proposed changes" in client.get(f"/applications/{app_id}/workbench").text


@pytest.mark.parametrize(
    "new",
    [
        "Built SQL reports for 999 customers.",
        "Led a team building SQL reports.",
        "Built SQL reports for financial transactions.",
        "Built Rust and SQL reports.",
    ],
)
def test_new_metrics_ownership_domain_or_tools_are_blocked(new):  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="unverified"):
        validate_edit(new, "Built SQL reports")


def test_legitimate_paraphrase_and_expanded_tool_name_are_allowed():
    source = "Built a Python pipeline on GCP for 500 tickets."
    bullets = ["Developed a Python pipeline on Google Cloud Platform for 500 tickets."]
    rewriter.validate_role(bullets[0], bullets, source, [source])
    with pytest.raises(ValueError, match="metrics"):
        rewriter.validate_role(
            "Built a Python pipeline on GCP.", ["Built a Python pipeline on GCP."], source, [source]
        )


def test_profile_change_during_inference_invalidates_proposal(app, monkeypatch):  # type: ignore[no-untyped-def]
    app_id = setup_workbench(app)
    provider = inject(monkeypatch, reply(app, app_id))
    generate = provider.generate

    def changed(prompt, timeout):  # type: ignore[no-untyped-def]
        with app.state.session_factory() as other:
            application = other.get(Application, app_id)
            other.get(Job, application.job_id).description_hash = "changed-in-flight"
            other.commit()
        return generate(prompt, timeout)

    provider.generate = changed
    with app.state.session_factory() as session, pytest.raises(ValueError, match="changed during"):
        rewriter.propose(session, app_id, Path(app.state.settings.data_dir), app.state.settings)
    assert not rewriter.load(Path(app.state.settings.data_dir), app_id)
