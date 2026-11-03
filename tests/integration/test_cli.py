from pathlib import Path

import pytest

from careeros.config import get_settings
from careeros.db.migrations import current_revision, head_revision
from careeros.db.session import create_sqlite_engine
from careeros.main import run


def test_migrate_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "data" / "cli.db"
    url = f"sqlite:///{db}"
    monkeypatch.chdir(tmp_path)  # keep any relative dirs inside tmp
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    get_settings.cache_clear()
    try:
        run(["migrate"])
    finally:
        get_settings.cache_clear()
    assert "latest migration" in capsys.readouterr().out
    engine = create_sqlite_engine(url)
    assert current_revision(engine) == head_revision(url)
    engine.dispose()
