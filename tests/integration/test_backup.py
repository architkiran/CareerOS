import io
import json
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from careeros.config import Settings, get_settings
from careeros.main import run
from careeros.modules.backup import service as backup


def _count(db: Path) -> int:
    with sqlite3.connect(db) as c:
        return int(c.execute("SELECT count(*) FROM activity_event").fetchone()[0])


def _add_event(db: Path, msg: str) -> None:
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO activity_event (event_type, message, metadata_json, created_at) "
            "VALUES ('t', ?, '{}', '2026-11-03 00:00:00')",
            (msg,),
        )


@pytest.fixture
def env(migrated_settings: Settings) -> tuple[Settings, Path]:
    docs = migrated_settings.data_dir / "documents" / "app1"
    docs.mkdir(parents=True)
    (docs / "resume-v1.docx").write_bytes(b"PK fake docx")
    db = backup.db_path(migrated_settings.database_url)
    _add_event(db, "original")
    return migrated_settings, db


def test_backup_and_verify(env: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, _ = env
    r = backup.create_backup(
        settings.database_url,
        settings.data_dir,
        tmp_path / "bk",
        now=datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
    )
    assert r.path.name == "careeros-backup-20261103-120000.tar.gz" and r.files == 2
    assert oct(r.path.stat().st_mode)[-3:] == "600"
    manifest = backup.verify_backup(r.path)
    assert set(manifest["files"]) == {"careeros.db", "documents/app1/resume-v1.docx"}  # type: ignore[arg-type]
    found = backup.latest_backup(tmp_path / "bk")
    assert found is not None and found[0] == r.path


def test_restore_round_trip_keeps_previous_db(env: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db = env
    r = backup.create_backup(settings.database_url, settings.data_dir, tmp_path / "bk")
    _add_event(db, "after backup")
    (settings.data_dir / "documents" / "app1" / "resume-v1.docx").write_bytes(b"changed")
    before = _count(db)
    moved = backup.restore_backup(
        r.path,
        settings.database_url,
        settings.data_dir,
        now=datetime(2026, 11, 3, 13, 0, tzinfo=UTC),
    )
    assert _count(db) == before - 1
    assert moved is not None and moved.exists() and _count(moved) == before  # nothing deleted
    assert (
        settings.data_dir / "documents" / "app1" / "resume-v1.docx"
    ).read_bytes() == b"PK fake docx"
    assert (settings.data_dir / "documents.before-restore-20261103-130000").is_dir()


def test_tampered_backup_refused(env: tuple[Settings, Path], tmp_path: Path) -> None:
    settings, db = env
    r = backup.create_backup(settings.database_url, settings.data_dir, tmp_path / "bk")
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(r.path, "r:gz") as src, tarfile.open(bad, "w:gz") as dst:
        for m in src.getmembers():
            data = src.extractfile(m).read()  # type: ignore[union-attr]
            if m.name.endswith(".docx"):
                data = b"tampered"
                m.size = len(data)
            dst.addfile(m, io.BytesIO(data))
    with pytest.raises(backup.BackupError, match="Hash mismatch"):
        backup.verify_backup(bad)
    before = _count(db)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(bad, settings.database_url, settings.data_dir)
    assert _count(db) == before  # untouched


def test_path_traversal_refused(tmp_path: Path) -> None:
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        for name, data in [
            ("manifest.json", json.dumps({"files": {"../escape": "x"}}).encode()),
            ("../escape", b"x"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with pytest.raises(backup.BackupError, match="Unsafe"):
        backup.verify_backup(evil)


def test_missing_and_garbage_archives(tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError, match="not found"):
        backup.verify_backup(tmp_path / "nope.tar.gz")
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not a tarball")
    with pytest.raises(backup.BackupError, match="Can't read"):
        backup.verify_backup(junk)


def test_memory_db_rejected() -> None:
    with pytest.raises(backup.BackupError):
        backup.db_path("sqlite:///:memory:")


def test_cli_backup_restore(
    env: tuple[Settings, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, db = env
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))

    def cli(*argv: str) -> int:
        get_settings.cache_clear()
        try:
            run(list(argv))
        except SystemExit as exc:
            return int(exc.code or 0)
        finally:
            get_settings.cache_clear()
        return 0

    assert cli("backup") == 0
    out = capsys.readouterr().out
    archive = out.split("verified: ")[1].split(" (")[0]
    assert cli("backup", "--verify", archive) == 0 and "OK: 2 files" in capsys.readouterr().out
    assert cli("restore", archive) == 1 and "--yes" in capsys.readouterr().err
    assert (
        cli("restore", archive, "--yes") == 0
        and "Previous database kept" in capsys.readouterr().out
    )
    assert cli("backup", "--verify", str(tmp_path / "missing.tar.gz")) == 1


def test_serve_refuses_network_bind(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from careeros import main

    called: list[bool] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: called.append(True))
    s = Settings(_env_file=None, app_host="0.0.0.0", worker_enabled=False)  # type: ignore[call-arg]  # noqa: S104
    with pytest.raises(SystemExit) as info:
        main._serve(s)
    assert info.value.code == 2 and not called and "Refusing" in capsys.readouterr().err
