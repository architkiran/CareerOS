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


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'data' / 'cli.db'}"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    get_settings.cache_clear()
    return url


def _run(argv: list[str]) -> int:
    try:
        run(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        get_settings.cache_clear()
    return 0


def test_ingest_requires_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(tmp_path, monkeypatch)
    assert _run(["ingest"]) == 1
    assert "careeros migrate" in capsys.readouterr().err


def test_sources_sync_list_and_ingest_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _env(tmp_path, monkeypatch)
    _run(["migrate"])
    assert _run(["sources", "sync"]) == 1  # file missing
    assert "Watchlist not found" in capsys.readouterr().err
    (tmp_path / "bad.toml").write_text("not = [valid")
    assert _run(["sources", "sync", "--file", "bad.toml"]) == 1
    assert "Invalid watchlist" in capsys.readouterr().err
    (tmp_path / "s.toml").write_text(
        '[[source]]\ntype="lever"\ntoken="acme"\nname="Acme"\nenabled=false\n'
    )
    assert _run(["sources", "sync", "--file", "s.toml"]) == 0
    assert "1 added" in capsys.readouterr().out
    assert _run(["sources", "list"]) == 0
    assert "acme" in capsys.readouterr().out
    assert _run(["ingest"]) == 0  # only source is disabled → nothing to fetch
    assert "No enabled sources" in capsys.readouterr().out
    assert _run(["ingest", "--token", "nope"]) == 1


def test_example_watchlist_is_valid() -> None:
    from careeros.modules.sources.registry import load_watchlist

    entries = load_watchlist(Path(__file__).parents[2] / "config" / "sources.example.toml")
    assert {e.type for e in entries} == {"greenhouse", "lever", "ashby", "smartrecruiters"}
