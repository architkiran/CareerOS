import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from careeros.config import Settings
from careeros.db.models import ActivityEvent, Task
from careeros.db.session import create_sqlite_engine, make_session_factory
from careeros.modules.backup.service import BackupError, db_path, verify_backup
from careeros.modules.backup.workspace import clone_workspace
from careeros.modules.scheduler import queue


def test_copy_keeps_source_and_cancels_pending_work_only_in_copy(
    migrated_settings: Settings,
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(migrated_settings.database_url)
    with make_session_factory(engine)() as session:
        task, _ = queue.enqueue(session, "ingest.all")
        session.commit()
        task_id = task.id
    engine.dispose()
    target = tmp_path / "new-workspace"
    result = clone_workspace(
        db_path(migrated_settings.database_url),
        migrated_settings.data_dir,
        target,
        tmp_path / "backups",
    )
    verify_backup(result.backup_path)
    assert result.cancelled_tasks == 1
    copied_engine = create_sqlite_engine(result.database_url)
    with make_session_factory(copied_engine)() as session:
        assert session.get(Task, task_id).status == "cancelled"
        assert session.scalars(
            select(ActivityEvent).where(ActivityEvent.event_type == "workspace.copied")
        ).one()
    copied_engine.dispose()
    with sqlite3.connect(db_path(migrated_settings.database_url)) as conn:
        assert (
            conn.execute("SELECT status FROM task WHERE id=?", (task_id,)).fetchone()[0] == "queued"
        )
    with pytest.raises(BackupError, match="already exists"):
        clone_workspace(
            db_path(migrated_settings.database_url),
            migrated_settings.data_dir,
            target,
            tmp_path / "backups",
        )


def test_storage_paths_rebase_only_within_known_roots(tmp_path: Path) -> None:
    from careeros.modules.backup.workspace import _relocated_path

    source = tmp_path / "old" / "data"
    destination = tmp_path / "new"
    copied = destination / "documents" / "application" / "resume.docx"
    copied.parent.mkdir(parents=True)
    copied.write_bytes(b"example")
    for value in [
        str(source / "documents/application/resume.docx"),
        "data/documents/application/resume.docx",
        "/app/data/documents/application/resume.docx",
    ]:
        assert _relocated_path(value, source, destination, (Path("/app/data"),)) == copied
    with pytest.raises(BackupError, match="outside"):
        _relocated_path("/etc/passwd", source, destination, ())


def test_copy_refuses_source_descendant(migrated_settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="separate"):
        clone_workspace(
            db_path(migrated_settings.database_url),
            migrated_settings.data_dir,
            migrated_settings.data_dir / "nested",
            tmp_path / "backups",
        )
