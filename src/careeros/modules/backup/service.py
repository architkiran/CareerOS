"""Verified local backups and safe restore.

A backup is a .tar.gz containing a consistent SQLite copy (via the backup API),
the private document/approval/outreach files, and a manifest of SHA-256
hashes. Restore verifies everything first and never deletes the current
database: it is moved aside as careeros.db.before-restore-<timestamp>.
"""

import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy.engine import make_url

from careeros import __version__
from careeros.common.fs import private_dir

PRIVATE_DIRS = ("documents", "approvals", "outreach", "resume_references")
DB_NAME = "careeros.db"
MANIFEST = "manifest.json"


class BackupError(Exception):
    pass


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def db_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError("Backups need a file-based SQLite database.")
    return Path(url.database)


@dataclass
class BackupResult:
    path: Path
    files: int
    db_bytes: int


def create_backup(
    database_url: str, data_dir: Path, dest_dir: Path, now: datetime | None = None
) -> BackupResult:
    src = db_path(database_url)
    if not src.exists():
        raise BackupError(f"Database not found at {src}")
    private_dir(dest_dir)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    archive = dest_dir / f"careeros-backup-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp)
        db_copy = staged / DB_NAME
        with sqlite3.connect(src) as live, sqlite3.connect(db_copy) as copy:
            live.backup(copy)
        files: dict[str, str] = {DB_NAME: _sha(db_copy)}
        for name in PRIVATE_DIRS:
            folder = data_dir / name
            if folder.is_dir():
                for f in sorted(p for p in folder.rglob("*") if p.is_file()):
                    rel = PurePosixPath(name, *f.relative_to(folder).parts)
                    target = staged / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, target)
                    files[str(rel)] = _sha(target)
        manifest = {"careeros_version": __version__, "created_at": stamp, "files": files}
        (staged / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
        with tarfile.open(archive, "w:gz") as tar:
            for name in [MANIFEST, *files]:
                tar.add(staged / name, arcname=name)
    archive.chmod(0o600)
    verify_backup(archive)
    return BackupResult(archive, len(files), db_copy_size(archive))


def db_copy_size(archive: Path) -> int:
    with tarfile.open(archive, "r:gz") as tar:
        return tar.getmember(DB_NAME).size


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = tar.getmembers()
    for m in members:
        p = PurePosixPath(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise BackupError(f"Unsafe entry in archive: {m.name!r}")
    return members


def verify_backup(archive: Path) -> dict[str, object]:
    """Check every file hash and the database's integrity. Returns the manifest."""
    if not archive.is_file():
        raise BackupError(f"Backup not found: {archive}")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            _safe_members(tar)
            mf = tar.extractfile(MANIFEST)
            if mf is None:
                raise BackupError("Backup has no manifest.")
            manifest = json.loads(mf.read())
            files: dict[str, str] = manifest["files"]
            names = {m.name for m in tar.getmembers() if m.isfile()} - {MANIFEST}
            if names != set(files):
                raise BackupError("Backup contents don't match its manifest.")
            for name, expected in files.items():
                fh = tar.extractfile(name)
                assert fh is not None
                if hashlib.sha256(fh.read()).hexdigest() != expected:
                    raise BackupError(f"Hash mismatch for {name}; the backup is damaged.")
            db_bytes = tar.extractfile(DB_NAME)
            assert db_bytes is not None
            with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                tmp.write(db_bytes.read())
                tmp.flush()
                with sqlite3.connect(tmp.name) as conn:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise BackupError("Database in the backup failed its integrity check.")
    except (tarfile.TarError, OSError, KeyError, json.JSONDecodeError) as exc:
        raise BackupError(f"Can't read backup: {type(exc).__name__}") from exc
    return dict(manifest)


def restore_backup(
    archive: Path, database_url: str, data_dir: Path, now: datetime | None = None
) -> Path | None:
    """Restore after verification. Returns where the previous database was moved, if any."""
    verify_backup(archive)
    target_db = db_path(database_url)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    moved: Path | None = None
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archive, "r:gz") as tar:
        staged = Path(tmp)
        for member in _safe_members(tar):
            if member.isfile():
                fh = tar.extractfile(member)
                assert fh is not None
                out = staged / member.name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(fh.read())
        target_db.parent.mkdir(parents=True, exist_ok=True)
        if target_db.exists():
            # Fold the write-ahead log into the main file so the moved copy is complete.
            with sqlite3.connect(target_db) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            moved = target_db.with_name(f"{target_db.name}.before-restore-{stamp}")
            target_db.rename(moved)
            for suffix in ("-wal", "-shm"):
                side = target_db.with_name(target_db.name + suffix)
                if side.exists():
                    side.rename(moved.with_name(moved.name + suffix))
        shutil.copy2(staged / DB_NAME, target_db)
        target_db.chmod(0o600)
        for name in PRIVATE_DIRS:
            src = staged / name
            if src.is_dir():
                dst = data_dir / name
                if dst.exists():
                    dst.rename(dst.with_name(f"{name}.before-restore-{stamp}"))
                shutil.copytree(src, dst)
                private_dir(dst)
    return moved


def latest_backup(dest_dir: Path) -> tuple[Path, datetime] | None:
    found = sorted(dest_dir.glob("careeros-backup-*.tar.gz")) if dest_dir.is_dir() else []
    if not found:
        return None
    stamp = found[-1].name.removeprefix("careeros-backup-").removesuffix(".tar.gz")
    try:
        when = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return found[-1], when
