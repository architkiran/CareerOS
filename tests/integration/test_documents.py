from datetime import date
from pathlib import Path

import pytest
from docx import Document as Docx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.db.models import Application, Company, Document, DocumentClaim, Job
from careeros.modules.applications import service as apps
from careeros.modules.documents import service as docs
from careeros.modules.profile import service as profile_service
from careeros.modules.profile.schemas import ExperienceIn, FactIn, ProfileIn, ProjectIn, SkillIn
from tests.conftest import post_form


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


@pytest.fixture
def data_dir(app: FastAPI) -> Path:
    return Path(app.state.settings.data_dir)


def _setup(f: sessionmaker[Session], *, dated: bool = True) -> str:
    with f() as s:
        profile_service.update_profile(
            s, ProfileIn(display_name="Test Person", email="t@example.com")
        )
        profile_service.add_fact(
            s,
            FactIn(
                category="education",
                fact_key="Degree",
                fact_value="MS Computer Science, Example U",
                verified_status="verified",
            ),
        )
        for n in ("SQL", "Python"):
            profile_service.add_skill(s, SkillIn(name=n, verified_status="verified"))
        profile_service.add_skill(s, SkillIn(name="Rust"))  # unverified
        profile_service.add_experience(
            s,
            ExperienceIn(
                organization="Example Org",
                title="Data Analyst",
                start_date=date(2026, 1, 5) if dated else None,
                end_date=date(2026, 5, 1) if dated else None,
                description="Built SQL reports",
                verified_status="verified",
            ),
        )
        profile_service.add_project(
            s,
            ProjectIn(
                name="Recon",
                technologies=["Python"],
                outcomes=["Checked 1,560 rows"],
                verified_status="verified",
            ),
        )
        c = Company(canonical_name="Acme", normalized_name="acme")
        s.add(c)
        s.flush()
        j = Job(
            canonical_url="https://acme.example/1",
            company_id=c.id,
            title="Data Analyst",
            normalized_title="data analyst",
            description_text="SQL and Python",
            description_hash="h",
            dedupe_key="k",
        )
        s.add(j)
        s.commit()
        return j.id


def test_generate_resume_files_claims_and_status(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        doc = docs.generate(s, app.id, "resume", data_dir)
        s.commit()
        assert doc.version == 1 and doc.status == "needs_ack"  # 1 unverified skill excluded
        assert [f["check"] for f in doc.qa_json] == ["unverified_excluded"]
        path = Path(doc.storage_path)
        assert path.is_file() and path.with_suffix(".json").is_file()
        assert (
            oct(path.stat().st_mode)[-3:] == "600" and oct(path.parent.stat().st_mode)[-3:] == "700"
        )
        text = "\n".join(p.text for p in Docx(str(path)).paragraphs)
        assert "Test Person" in text and "Data Analyst, Example Org" in text and "Rust" not in text
        claims = s.scalars(select(DocumentClaim).where(DocumentClaim.document_id == doc.id)).all()
        assert claims and all(c.supporting_profile_fact_ids_json for c in claims)
        assert all(c.verification_status == "supported" for c in claims)


def test_unchanged_regeneration_reuses_version(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        a = docs.generate(s, app.id, "resume", data_dir)
        b = docs.generate(s, app.id, "resume", data_dir)
        assert a.id == b.id and len(s.scalars(select(Document)).all()) == 1


def test_profile_change_creates_new_version_with_diff(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        v1 = docs.generate(s, app.id, "resume", data_dir)
        profile_service.add_skill(s, SkillIn(name="Tableau", verified_status="verified"))
        v2 = docs.generate(s, app.id, "resume", data_dir)
        s.commit()
        assert (v1.version, v2.version) == (1, 2) and v1.storage_path != v2.storage_path
        assert Path(v1.storage_path).is_file()  # old versions are kept
        prev, lines = docs.diff(s, v2.id)
        assert prev is not None and prev.id == v1.id
        assert any(line.startswith("+") and "Tableau" in line for line in lines)
        _, first = docs.diff(s, v1.id)
        assert first[0].startswith("--- (none)")


def test_acknowledge_and_ready_sync(factory: sessionmaker[Session], data_dir: Path) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        doc = docs.generate(s, app.id, "resume", data_dir)
        docs.acknowledge(s, doc.id)
        assert doc.status == "ready" and doc.warnings_acknowledged_at
        apps.sync_ready(s, app, True)
        assert app.status == "ready"
        apps.sync_ready(s, app, False)
        assert app.status == "preparing"


def test_blocked_version_cannot_be_acknowledged(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        doc = docs.generate(s, app.id, "resume", data_dir)
        doc.status = "blocked"
        with pytest.raises(docs.DocumentError, match="errors"):
            docs.acknowledge(s, doc.id)


def test_tampered_file_detected(factory: sessionmaker[Session], data_dir: Path) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        doc = docs.generate(s, app.id, "resume", data_dir)
        Path(doc.storage_path).with_suffix(".json").write_text('{"tampered": true}')
        with pytest.raises(docs.DocumentError, match="hash"):
            docs.load_content(doc)


@pytest.mark.parametrize("artifact", ["binary", "json", "missing", "legacy"])
def test_integrity_failure_requires_new_immutable_version(
    factory: sessionmaker[Session], data_dir: Path, client: TestClient, artifact: str
) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        old = docs.generate(s, app.id, "resume", data_dir)
        path = Path(old.storage_path)
        if artifact == "binary":
            path.write_bytes(b"altered Word content")
        elif artifact == "json":
            path.with_suffix(".json").write_text("{}")
        elif artifact == "missing":
            path.unlink()
        else:
            old.file_hash = None
        s.commit()
        assert docs.integrity_error(old)
        with pytest.raises(docs.DocumentError):
            docs.acknowledge(s, old.id)
        response = client.get(f"/documents/{old.id}/download")
        assert response.status_code == (404 if artifact == "missing" else 409)
        assert (
            'data-testid="document-integrity-error"' in client.get(f"/applications/{app.id}").text
        )
        original_bytes = path.read_bytes() if path.exists() else None
        new = docs.generate(s, app.id, "resume", data_dir)
        assert new.version == old.version + 1 and new.storage_path != old.storage_path
        assert old.file_hash is None if artifact == "legacy" else old.file_hash
        docs.verify_integrity(new)
        if original_bytes is not None:
            assert path.read_bytes() == original_bytes


def test_no_profile_is_a_clear_error(factory: sessionmaker[Session], data_dir: Path) -> None:
    with factory() as s:
        c = Company(canonical_name="A", normalized_name="a")
        s.add(c)
        s.flush()
        j = Job(
            canonical_url="https://a/1",
            company_id=c.id,
            title="T",
            normalized_title="t",
            description_hash="h",
            dedupe_key="k",
        )
        s.add(j)
        s.flush()
        app = apps.start_application(s, j.id)
        with pytest.raises(docs.DocumentError, match="profile"):
            docs.generate(s, app.id, "resume", data_dir)


def test_status_rules(factory: sessionmaker[Session]) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        assert apps.start_application(s, jid).id == app.id
        with pytest.raises(apps.ApplicationError, match="Can't move"):
            apps.set_status(s, app.id, "submitted")  # only via approval flow
        with pytest.raises(apps.ApplicationError, match="Can't move"):
            apps.set_status(s, app.id, "interview")
        with pytest.raises(apps.ApplicationError, match="Unknown"):
            apps.set_status(s, app.id, "hired", system=True)
        apps.set_status(s, app.id, "submitted", system=True)
        apps.set_status(s, app.id, "screen", "Recruiter call booked")
        apps.set_status(s, app.id, "rejected")
        assert app.outcome == "rejected"
        assert apps.TRANSITIONS["rejected"] == ()
        events = [e.event_type for e in apps.history(s, app.id)]
        assert events[-1] == "created" and "status:screen" in events


# ---------- web ----------


def test_application_pages_end_to_end(factory: sessionmaker[Session], client: TestClient) -> None:
    jid = _setup(factory, dated=False)
    assert 'data-testid="applications-empty"' in client.get("/applications").text
    assert 'data-testid="start-application"' in client.get(f"/jobs/{jid}").text
    r = post_form(client, f"/jobs/{jid}/application")
    app_url = r.headers["location"]
    assert (
        r.status_code == 303 and 'data-testid="open-application"' in client.get(f"/jobs/{jid}").text
    )
    page = client.get(app_url).text
    assert 'data-testid="docs-empty"' in page and 'data-testid="app-status">preparing<' in page
    app_id = app_url.rsplit("/", 1)[1]
    assert (
        post_form(
            client, f"/applications/{app_id}/documents", {"document_type": "resume"}
        ).status_code
        == 303
    )
    page = client.get(app_url).text
    assert 'data-testid="doc-status-resume">needs ack<' in page and "no start date" in page
    with factory() as s:
        doc = s.scalars(select(Document)).one()
    dl = client.get(f"/documents/{doc.id}/download")
    assert (
        dl.status_code == 200
        and dl.content[:2] == b"PK"
        and dl.headers["cache-control"] == "no-store"
    )
    post_form(client, f"/documents/{doc.id}/acknowledge")
    page = client.get(app_url).text
    assert (
        'data-testid="doc-status-resume">ready<' in page
        and 'data-testid="app-status">ready<' in page
    )
    post_form(client, f"/applications/{app_id}/documents", {"document_type": "cover_letter"})
    assert 'data-testid="doc-cover_letter"' in client.get(app_url).text
    assert client.get("/applications").text.count('data-testid="application-row"') == 1
    bad = post_form(client, f"/applications/{app_id}/status", {"status": "submitted"})
    assert bad.status_code == 422 and "move from ready to submitted" in bad.text
    assert (
        post_form(
            client, f"/applications/{app_id}/documents", {"document_type": "memo"}
        ).status_code
        == 422
    )
    post_form(client, f"/applications/{app_id}/notes", {"notes": "<i>call back</i>"})
    assert "&lt;i&gt;call back" in client.get(app_url).text


def test_download_rejects_paths_outside_data_dir(
    factory: sessionmaker[Session], client: TestClient, tmp_path: Path
) -> None:
    jid = _setup(factory)
    outside = tmp_path / "secret.docx"
    outside.write_text("x")
    with factory() as s:
        app = apps.start_application(s, jid)
        doc = Document(
            application_id=app.id,
            document_type="resume",
            version=1,
            storage_path=str(outside),
            content_hash="x",
            base_template_id="t",
            status="ready",
        )
        s.add(doc)
        s.commit()
        did = doc.id
    assert client.get(f"/documents/{did}/download").status_code == 404
    assert client.get("/documents/missing/download").status_code == 404
    assert client.get("/applications/missing").status_code == 404
    assert post_form(client, "/jobs/missing/application").status_code == 404


def test_diff_page(factory: sessionmaker[Session], client: TestClient, data_dir: Path) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        docs.generate(s, app.id, "resume", data_dir)
        profile_service.add_skill(s, SkillIn(name="Excel", verified_status="verified"))
        v2 = docs.generate(s, app.id, "resume", data_dir)
        s.commit()
        vid = v2.id
    html = client.get(f"/documents/{vid}/diff").text
    assert 'data-testid="diff"' in html and "Excel" in html and 'class="add"' in html
    assert client.get(f"/applications/{app.id}").status_code == 200
    with factory() as s:
        assert s.get(Application, app.id) is not None
