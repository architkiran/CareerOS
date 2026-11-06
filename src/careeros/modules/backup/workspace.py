"""Copy an existing local workspace without replacing either source or destination data."""

import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from careeros.common.clock import utcnow
from careeros.common.fs import private_dir
from careeros.db.migrations import upgrade_to_head
from careeros.db.models import (
    AgentAttempt,
    AgentRun,
    Approval,
    Document,
    Mission,
    OutreachDraft,
    PipelineRun,
    SourceRun,
    Task,
)
from careeros.db.session import create_sqlite_engine, make_session_factory
from careeros.modules.backup import service
from careeros.modules.events.service import record_event


@dataclass(frozen=True)
class WorkspaceCopy:
    data_dir: Path
    database_url: str
    backup_path: Path
    relocated_files: int
    cancelled_tasks: int


def _relocated_path(
    value: str, source_data: Path, destination: Path, aliases: tuple[Path, ...]
) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = source_data.parent / path
    path = path.resolve()
    for root in (source_data, *aliases):
        try:
            relative = path.relative_to(root.resolve())
        except ValueError:
            continue
        if not relative.parts or relative.parts[0] not in service.PRIVATE_DIRS:
            break
        relocated = destination / relative
        if relocated.is_file() and relocated.resolve().is_relative_to(destination):
            return relocated
        raise service.BackupError("A referenced private artifact is missing from the copy.")
    raise service.BackupError("A stored artifact path is outside the configured data roots.")


def clone_workspace(
    source_database: Path,
    source_data: Path,
    destination: Path,
    backup_dir: Path,
    *,
    storage_aliases: tuple[Path, ...] = (),
) -> WorkspaceCopy:
    """Read source SQLite in read-only mode, verify a backup, restore into a NEW folder.

    The caller supplies known legacy storage aliases, e.g. Docker's /app/data. This
    never infers arbitrary file locations. On error the partial copy is retained
    for inspection; no existing directory or database is deleted or overwritten.
    """
    source_database, source_data = source_database.resolve(), source_data.resolve()
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise service.BackupError("Destination already exists; choose a new empty workspace path.")
    if destination.resolve().is_relative_to(source_data):
        raise service.BackupError("Destination must be separate from the source data directory.")
    if not source_database.is_file():
        raise service.BackupError("Source database not found.")
    # Refuse symlinks before the existing archiver follows them.
    for name in service.PRIVATE_DIRS:
        folder = source_data / name
        if folder.is_symlink() or (
            folder.exists() and any(p.is_symlink() for p in folder.rglob("*"))
        ):
            raise service.BackupError("Private artifact folders must not contain symlinks.")
    private_dir(backup_dir)
    with tempfile.TemporaryDirectory(dir=backup_dir) as temporary:
        snapshot = Path(temporary) / "snapshot.db"
        with (
            sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True) as source,
            sqlite3.connect(snapshot) as target,
        ):
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise service.BackupError("Snapshot failed its integrity check.")
        snapshot.chmod(0o600)
        backup = service.create_backup(f"sqlite:///{snapshot}", source_data, backup_dir)
    destination.mkdir(parents=True, exist_ok=False)
    private_dir(destination)
    database_url = f"sqlite:///{destination / service.DB_NAME}"
    service.restore_backup(backup.path, database_url, destination)
    upgrade_to_head(database_url)
    engine = create_sqlite_engine(database_url)
    relocated = cancelled = 0
    try:
        with make_session_factory(engine)() as session:
            for doc in session.scalars(select(Document)):
                doc.storage_path = str(
                    _relocated_path(doc.storage_path, source_data, destination, storage_aliases)
                )
                relocated += 1
            for approval in session.scalars(select(Approval)):
                approval.payload_snapshot_path = str(
                    _relocated_path(
                        approval.payload_snapshot_path, source_data, destination, storage_aliases
                    )
                )
                relocated += 1
            for draft in session.scalars(select(OutreachDraft)):
                draft.body_path = str(
                    _relocated_path(draft.body_path, source_data, destination, storage_aliases)
                )
                relocated += 1
            # Never replay copied work or impersonate a source worker. History remains.
            for task in session.scalars(select(Task).where(Task.status.in_(["queued", "running"]))):
                task.status, task.finished_at = "cancelled", utcnow()
                task.locked_by = task.locked_until = None
                cancelled += 1
            for mission in session.scalars(
                select(Mission).where(Mission.status.in_(["queued", "running", "paused"]))
            ):
                mission.status, mission.finished_at = "cancelled", utcnow()
            for run in session.scalars(
                select(AgentRun).where(
                    AgentRun.status.in_(["blocked", "queued", "running", "retrying"])
                )
            ):
                run.status, run.finished_at = "cancelled", utcnow()
            for attempt in session.scalars(
                select(AgentAttempt).where(AgentAttempt.status == "running")
            ):
                attempt.status, attempt.finished_at = "interrupted", utcnow()
            for pipeline in session.scalars(
                select(PipelineRun).where(PipelineRun.status == "running")
            ):
                pipeline.status, pipeline.finished_at = "interrupted", utcnow()
            for source_run in session.scalars(
                select(SourceRun).where(SourceRun.status == "running")
            ):
                source_run.status, source_run.finished_at = "interrupted", utcnow()
            record_event(
                session,
                "workspace.copied",
                "Workspace copied safely; start a new review when ready.",
                metadata={"relocated_files": relocated, "cancelled_tasks": cancelled},
            )
            session.commit()
    finally:
        engine.dispose()
    return WorkspaceCopy(destination, database_url, backup.path, relocated, cancelled)
