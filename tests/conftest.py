from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from careeros.config import Settings
from careeros.db.migrations import upgrade_to_head
from careeros.main import create_app
from careeros.web.csrf import COOKIE_NAME as CSRF_COOKIE


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        database_url=f"sqlite:///{data / 'test.db'}",
        data_dir=data,
        export_dir=tmp_path / "exports",
        backup_dir=tmp_path / "backups",
        worker_enabled=False,
    )


@pytest.fixture
def migrated_settings(settings: Settings) -> Settings:
    settings.ensure_private_dirs()
    upgrade_to_head(settings.database_url)
    return settings


@pytest.fixture
def app(migrated_settings: Settings) -> Iterator[FastAPI]:
    application = create_app(migrated_settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(app: FastAPI) -> Iterator[Session]:
    with app.state.session_factory() as s:
        yield s


def csrf_token(client: TestClient) -> str:
    """Return the client's CSRF token, fetching a page first if needed."""
    token = client.cookies.get(CSRF_COOKIE)
    if not token:
        client.get("/health")
        token = client.cookies.get(CSRF_COOKIE)
    assert token
    return token


def post_form(client: TestClient, url: str, data: dict[str, object] | None = None, **kw: object):  # type: ignore[no-untyped-def]
    payload = {"csrf_token": csrf_token(client), **(data or {})}
    return client.post(url, data=payload, follow_redirects=False, **kw)  # type: ignore[arg-type]


@pytest.fixture
def pdf_compiler(monkeypatch):  # type: ignore[no-untyped-def]
    """Offline compiler stand-in for route tests; actual compilation is validated separately."""
    from pypdf import PdfWriter

    from careeros.modules.documents import latex

    def compile_pdf(content, path):
        path.with_suffix(".tex").write_text(latex.source(content))
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with path.open("wb") as stream:
            writer.write(stream)
        path.chmod(0o600)
        return []

    monkeypatch.setattr(latex, "compile_pdf", compile_pdf)
