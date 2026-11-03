"""Repair jobs wrongly merged by an over-eager URL canonicalizer.

Before this fix, `gh_jid` was stripped from URLs, so company-hosted Greenhouse
boards (e.g. stripe.com/jobs/search?gh_jid=123) collapsed into a single job.

This migration:
1. keeps the earliest source record on each affected job and deletes the other
   records from the *same* source, so the next ingest recreates them as
   separate jobs (raw data is refetched from the source);
2. recomputes every job's canonical_url with the corrected rule.

No jobs are deleted, and user triage and overrides on kept jobs are untouched.
Downgrade is a no-op: the wrong merge is not worth reproducing.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the corrected rule so this migration never changes meaning later.
_TRACKING = {"gh_src", "lever-source", "lever-origin"}


def _canonical(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(sorted(query)), "")
    )


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, job_id, source_id, source_url FROM job_source_record "
            "ORDER BY job_id, source_id, first_seen_at, id"
        )
    ).all()
    kept: dict[tuple[str, str], str] = {}
    first_url: dict[str, str] = {}
    drop: list[str] = []
    for rec_id, job_id, source_id, source_url in rows:
        first_url.setdefault(job_id, source_url)
        if (job_id, source_id) in kept:
            drop.append(rec_id)
        else:
            kept[(job_id, source_id)] = rec_id
    for i in range(0, len(drop), 500):
        chunk = drop[i : i + 500]
        conn.execute(
            sa.text("DELETE FROM job_source_record WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": chunk},
        )
    for job_id, url in first_url.items():
        conn.execute(
            sa.text("UPDATE job SET canonical_url = :u WHERE id = :j"),
            {"u": _canonical(url), "j": job_id},
        )
    if drop:
        conn.execute(
            sa.text(
                "INSERT INTO activity_event (event_type, message, metadata_json, created_at) "
                "VALUES ('system.repair', :m, '{}', CURRENT_TIMESTAMP)"
            ),
            {
                "m": f"Repaired {len(drop)} job listings that had been wrongly merged. "
                "Run discovery to fetch them as separate jobs."
            },
        )


def downgrade() -> None:
    pass
