from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter

from careeros.modules.applications.service import start_application
from careeros.modules.approvals import service as gate
from careeros.modules.documents import latex
from careeros.modules.documents import service as docs
from careeros.modules.documents.content import experience_paragraphs
from tests.conftest import post_form
from tests.integration.test_documents import _setup


@pytest.fixture
def fake_compiler(monkeypatch):  # type: ignore[no-untyped-def]
    calls = []
    monkeypatch.setattr(latex, "compiler_path", lambda: Path("/local/tectonic"))

    def run(args, **kwargs):
        assert "--untrusted" in args and "--only-cached" in args
        assert "shell" not in kwargs
        path = Path(kwargs["cwd"]) / Path(args[-1]).with_suffix(".pdf")
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with path.open("wb") as stream:
            writer.write(stream)
        path.with_suffix(".log").write_text("")
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(latex.subprocess, "run", run)
    return calls


def test_pdf_generation_integrity_names_and_versioning(app, client, fake_compiler):  # type: ignore[no-untyped-def]
    factory = app.state.session_factory
    job_id = _setup(factory)
    with factory() as session:
        application = start_application(session, job_id)
        d = docs.generate(
            session, application.id, "resume", app.state.settings.data_dir, render_format="pdf"
        )
        assert d.storage_path.endswith(".pdf") and len(PdfReader(d.storage_path).pages) == 1
        assert "Rust" not in Path(d.storage_path).with_suffix(".tex").read_text()
        assert (
            docs.generate(
                session, application.id, "resume", app.state.settings.data_dir, render_format="pdf"
            ).id
            == d.id
        )
        docs.verify_integrity(d)
        session.commit()
        url = f"/documents/{d.id}/download"
        assert "Archit_Kiran_Kumar_Resume.pdf" in client.get(url).headers["content-disposition"]
        assert client.get(url + "?inline=true").headers["content-disposition"].startswith("inline;")
        docs.acknowledge(session, d.id)
        approval = gate.request(
            session,
            gate.application_payload(session, application.id, False),
            app.state.settings.data_dir,
        )
        Path(d.storage_path).with_suffix(".tex").write_text("tampered source")
        gate.refresh(session, approval)
        assert approval.status == "invalidated"
        session.commit()
        assert client.get(url).status_code == 409
    assert len(fake_compiler) == 1


def test_missing_compiler_does_not_substitute_word(app, monkeypatch):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    monkeypatch.setattr(latex, "compiler_path", lambda: None)
    with app.state.session_factory() as session:
        application = start_application(session, job_id)
        with pytest.raises(docs.DocumentError, match="compiler"):
            docs.generate(
                session, application.id, "resume", app.state.settings.data_dir, render_format="pdf"
            )
        assert docs.latest(session, application.id, "resume") is None


def test_injection_is_text_and_soft_wraps_are_joined():
    text = r"Hello & 5% $x$ \input{/etc/passwd} #1_2"
    safe = latex.escape(text)
    assert r"\input{" not in safe and r"\textbackslash{}" in safe and r"\%" in safe
    assert experience_paragraphs("Built a pipeline across\nthree teams.\nShipped a dashboard.") == [
        "Built a pipeline across three teams.",
        "Shipped a dashboard.",
    ]
    assert (
        experience_paragraphs("Jan to May 2026 per your resume notes. Add exact start/end dates.")
        == []
    )


def test_pdf_route_is_csrf_protected_and_studio_labels_role(app, client, fake_compiler):  # type: ignore[no-untyped-def]
    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as session:
        application = start_application(session, job_id)
        session.commit()
    path = f"/applications/{application.id}/resume-pdf"
    assert client.post(path).status_code == 403
    assert (
        post_form(client, path, {"project_limit": "3", "experience_limit": "2"}).status_code == 303
    )
    studio = client.get("/resumes")
    assert studio.status_code == 200 and "Data Analyst · Acme" in studio.text
    assert "Archit_Kiran_Kumar_Resume.pdf" in studio.text
    assert post_form(client, path, {"project_limit": "99"}).status_code == 422


def test_current_profile_verification_is_rechecked_at_approval(app):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    from careeros.db.models import CandidateSkill

    job_id = _setup(app.state.session_factory)
    with app.state.session_factory() as session:
        application = start_application(session, job_id)
        document = docs.generate(session, application.id, "resume", app.state.settings.data_dir)
        docs.acknowledge(session, document.id)
        gate.application_payload(session, application.id, False)
        skill = session.scalars(
            select(CandidateSkill).where(CandidateSkill.verified_status == "verified")
        ).first()
        skill.verified_status = "unverified"
        with pytest.raises(gate.ApprovalError, match="fact checks"):
            gate.application_payload(session, application.id, False)


def test_experience_without_bullets_has_no_empty_latex_list():
    from careeros.modules.documents.content import Claim, DocumentContent

    content = DocumentContent(
        "resume",
        "General",
        ["Candidate"],
        [("Experience", [Claim("Experience", "Analyst, Example", ["experience:a"])])],
    )
    assert "\\begin{itemize}\n\\end{itemize}" not in latex.source(content)
