"""Immutable PDF references. Registration never verifies claims or changes a template."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from careeros.common.fs import private_dir
from careeros.db.models import Setting
from careeros.modules.events.service import record_event
from careeros.modules.system.settings_store import get_setting, set_setting

PREFIX = "resumes.reference."
MAX_BYTES = 10_000_000
Family = Literal["analytics", "data_engineering", "project_management"]
LABELS = {
    "analytics": "Data, business & financial analysis",
    "data_engineering": "Data engineering",
    "project_management": "Project & product coordination",
}


class ReferenceError(ValueError):
    pass


class ResumeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    family: Family
    title: str = Field(min_length=1, max_length=150)
    size_bytes: int = Field(ge=1, le=MAX_BYTES)
    review_notes: list[str] = Field(default_factory=list, max_length=20)


def _path(data_dir: Path, reference_id: str) -> Path:
    if len(reference_id) != 32 or any(c not in "0123456789abcdef" for c in reference_id):
        raise LookupError("Resume reference not found")
    path = data_dir / "resume_references" / f"{reference_id}.pdf"
    if path.is_symlink() or path.parent.is_symlink():
        raise ReferenceError("Resume reference failed its integrity check.")
    return path


def register(
    session: Session,
    data_dir: Path,
    source: Path,
    *,
    family: Family,
    title: str,
    review_notes: list[str] | None = None,
) -> ResumeReference:
    # Read only a bounded amount; the file is reference data, never executable input.
    with source.open("rb") as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES or not content.startswith(b"%PDF-"):
        raise ReferenceError("Choose a PDF reference up to 10 MB.")
    digest = hashlib.sha256(content).hexdigest()
    reference = ResumeReference(
        id=digest[:32],
        sha256=digest,
        family=family,
        title=title,
        size_bytes=len(content),
        review_notes=review_notes or [],
    )
    existing = get_setting(session, PREFIX + reference.id)
    if existing:
        old = ResumeReference.model_validate(existing)
        if old.family != family or old.title != title:
            raise ReferenceError(
                "This PDF is already registered; its original metadata is immutable."
            )
        checked_path(data_dir, old)
        return old
    path = _path(data_dir, reference.id)
    folder = private_dir(path.parent)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ReferenceError("Resume reference failed its integrity check.")
    else:
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(0o600)
    assert folder == path.parent
    set_setting(session, PREFIX + reference.id, reference.model_dump())
    record_event(
        session,
        "resume.reference_added",
        "A private resume reference was added.",
        entity_type="resume_reference",
        entity_id=reference.id,
        metadata={"family": family},
    )
    return reference


def list_references(session: Session) -> list[ResumeReference]:
    rows = session.scalars(
        select(Setting).where(Setting.key.startswith(PREFIX)).order_by(Setting.key)
    )
    return [ResumeReference.model_validate(row.value_json) for row in rows]


def get_reference(session: Session, reference_id: str) -> ResumeReference:
    # Validate the ID before using it as either a setting key or file identifier.
    _path(Path("."), reference_id)
    value = get_setting(session, PREFIX + reference_id)
    if value is None:
        raise LookupError("Resume reference not found")
    return ResumeReference.model_validate(value)


def checked_path(data_dir: Path, reference: ResumeReference) -> Path:
    path = _path(data_dir, reference.id)
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ReferenceError("Resume reference is unavailable.") from exc
    if len(data) != reference.size_bytes or hashlib.sha256(data).hexdigest() != reference.sha256:
        raise ReferenceError("Resume reference failed its integrity check.")
    return path
