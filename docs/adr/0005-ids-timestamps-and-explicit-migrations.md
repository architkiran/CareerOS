# ADR 0005: IDs, timestamps, and explicit migrations

Status: Accepted

## Context
DATA_MODEL.md allows UUID or ULID string IDs and requires UTC timestamps and safe schema evolution.

## Decision
- Entity tables use UUID4 hex strings (`careeros.common.ids.new_id`), stdlib only.
- Append-only stream tables (`activity_event`) use integer autoincrement IDs so the SSE endpoint can resume from a monotonic cursor.
- Timestamps are stored as naive UTC in SQLite via `UTCDateTime`, returned timezone-aware, and naive inputs are rejected. Rendering converts to `DISPLAY_TIMEZONE`.
- Migrations run only via `careeros migrate`, never at app startup. Health reports `degraded` while migrations are pending.

## Consequences
No extra dependencies. UUID4 is not time-sortable, so ordering uses `created_at` columns. Users must run one explicit command after upgrades, which avoids surprise schema changes to their database.
