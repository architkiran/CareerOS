# Simplification audit — 10 November 2026

Baseline: 710 tests passed in 43.45s (`.venv/bin/pytest`). Branch starts at
`3c5b9db`. The user-authored `newchanges.md` remains intact. This audit precedes
implementation; the implementation report records subsequent verified behavior.

## Implemented today, before changes

- Seven public adapters plus manual intake normalize to `NormalizedJob`. The
  ingestion pipeline uses stable provider IDs, canonical URLs and description
  hashes. Repeated polls are tested; failed fetches preserve jobs.
- `Job.posted_at` already means source publication; `first_seen_at` and
  `last_seen_at` are separate. Raw payloads and original source URLs are retained
  in `JobSourceRecord`. Do not add a duplicate publication column on Job.
- Deterministic lane matching, hard pass/fail/unknown filters, accepted-evidence
  sponsorship research, private documents, application events and approval gates
  are functional and covered by tests. These are not stubs.
- Source monitoring uses persisted missions and queue idempotency. Public boards
  impose longer intervals. The worker pauses while the computer sleeps.
- The user journey is currently launch → Mission Control → Fresh jobs → split
  view → details → original URL. Preparing an application starts evidence and
  networking tasks. The tracker is a four-column kanban including unsubmitted
  preparation records. Submission recording requires package approval.

## Exact defects and changes

| Slice | Existing files/functions | Required change |
|---|---|---|
| Source times | `sources/schemas.py`, adapters, `ingestion/service.py::_apply/upsert_job`, `db/models/jobs.py` | Preserve modified/fetch times and per-source publication semantics; retain meaningful revision snapshots. Reuse `posted_at` for publication. |
| Closure | `ingestion/service.py::_close_unseen/run_source` | Track successful per-source presence; never infer closure from a failed/partial snapshot. Test multi-source absence. |
| URLs | `sources/text.py`, `ingestion/manual.py`, inbox presentation | Validate HTTP(S) host and credentials, retain destination/query/fragment, prefer exact employer/provider originals; expose unavailable links honestly. No live URL claim from syntax validation. |
| Scheduling | `sources/monitoring.py::coverage/tick`, `web/routes/watch.py` | Configurable 30-minute default with stricter provider limits; respect pause and queue idempotency; show stale/error, next check and actual observations. |
| Manual tracking | `applications/service.py`, `web/routes/applications.py` | Explicit user-confirmed record of an already completed external application, dated and idempotent, without documents/agents/approval prerequisites. Preserve optional package gates. |
| Main inbox | `jobs/service.py`, `web/routes/jobs.py`, new inbox presentation | New since review, source-date ordering, concise reasons, sponsorship evidence and save/dismiss/review actions. Paginate and keep uncertain roles visible. |
| Navigation | `base.html`, `system.py`, `local_launcher.py`, launch scripts | New Jobs, Saved Jobs, Applications only; direct original links dominate; retained advanced tools under one quiet disclosure. |
| Saved / applications | job inbox service and `applications.html` | Separate shortlist and manual application records; no forced document flow. Preserve earlier preparation records under Advanced. |
| Matching / metrics | existing matching contracts and analytics | Labeled evaluation fixtures; separate eligibility from ranking; actual source-delay, duplicate and action metrics with denominators and honest unknowns. |

## Implementation order and risks

1. Additive migration and source timestamp/history/closure tests.
2. Source-aware schedule and direct original-URL presentation; manual record path.
3. Three-screen UI, quiet optional capabilities, user review cursor.
4. Labeled matching evaluation, bounded metrics, full regression and browser checks.
5. Update docs/config to describe only verified behavior.

Main risks are losing job identity while changing URLs, asserting original
publication from a republish timestamp, closing jobs after incomplete feeds,
resetting the inbox review cursor on passive refresh, and treating a local
application record as an external submission. Tests must cover these boundaries.
No external applications, messages, payments, or new services are in scope.
