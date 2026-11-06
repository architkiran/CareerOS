from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from careeros.config import Settings
from careeros.modules.backup import service as backups
from careeros.modules.resumes import service


def test_reference_is_private_immutable_and_downloadable(
    session: Session,
    client: TestClient,
    settings: Settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "resume.pdf"
    content = b"%PDF-1.7\nreference bytes"
    source.write_bytes(content)
    reference = service.register(
        session,
        settings.data_dir,
        source,
        family="analytics",
        title="Analysis reference",
        review_notes=["Metrics need review."],
    )
    session.commit()
    assert (
        service.register(
            session, settings.data_dir, source, family="analytics", title="Analysis reference"
        ).id
        == reference.id
    )
    assert source.read_bytes() == content
    path = service.checked_path(settings.data_dir, reference)
    assert path.read_bytes() == content
    assert path.stat().st_mode & 0o777 == 0o600
    page = client.get("/resumes")
    assert page.status_code == 200 and "Analysis reference" in page.text
    assert "does not verify its claims" in page.text
    assert page.headers["cache-control"] == "no-store"
    download = client.get(f"/resumes/{reference.id}/download")
    assert download.content == content and "attachment;" in download.headers["content-disposition"]
    with pytest.raises(service.ReferenceError, match="immutable"):
        service.register(
            session, settings.data_dir, source, family="data_engineering", title="Other"
        )
    path.write_bytes(b"tampered")
    assert client.get(f"/resumes/{reference.id}/download").status_code == 409


def test_reference_input_boundaries(session: Session, settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "bad.pdf"
    source.write_bytes(b"not a PDF")
    with pytest.raises(service.ReferenceError):
        service.register(session, settings.data_dir, source, family="analytics", title="Invalid")
    source.write_bytes(b"%PDF-" + b"X" * service.MAX_BYTES)
    with pytest.raises(service.ReferenceError):
        service.register(session, settings.data_dir, source, family="analytics", title="Too big")
    with pytest.raises(LookupError):
        service.get_reference(session, "../escape")


def test_references_are_included_in_verified_backups(
    session: Session,
    settings: Settings,
    tmp_path: Path,
) -> None:
    source = tmp_path / "resume.pdf"
    source.write_bytes(b"%PDF-1.7\nprivate")
    reference = service.register(
        session, settings.data_dir, source, family="analytics", title="Ref"
    )
    session.commit()
    result = backups.create_backup(settings.database_url, settings.data_dir, tmp_path / "backups")
    manifest = backups.verify_backup(result.path)
    assert f"resume_references/{reference.id}.pdf" in manifest["files"]


def test_empty_library_and_unknown_reference(client: TestClient) -> None:
    assert "No resume references registered" in client.get("/resumes").text
    assert client.get("/resumes/" + "0" * 32 + "/download").status_code == 404


def test_reference_refuses_symlink_storage(
    session: Session, settings: Settings, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (settings.data_dir / "resume_references").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nprivate")
    with pytest.raises(service.ReferenceError):
        service.register(session, settings.data_dir, source, family="analytics", title="Blocked")
    assert list(outside.iterdir()) == []
