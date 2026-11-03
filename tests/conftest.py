from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from careeros.config import Settings
from careeros.db.migrations import upgrade_to_head
from careeros.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        database_url=f"sqlite:///{data / 'test.db'}",
        data_dir=data,
        export_dir=tmp_path / "exports",
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
