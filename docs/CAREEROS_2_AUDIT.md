# CareerOS 2.0 audit and first slice

Audit baseline: local clean `main` at `b95223c`, 203 tracked files. Work takes place
on `feature/careeros-2-mission-control` in an isolated checkout. The original
checkout, ignored personal files, database and exports are not copied or mutated.

## Baseline validation

Using the original checkout's existing Python 3.12 virtual environment, with this
checkout as cwd (pytest's pythonpath points to this checkout's src):

- `python -m pytest`: **476 passed in 23.40s**.
- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: 161 files formatted.
- `python -m mypy`: passed, 93 source files.

No packages, paid services, models or credits were purchased or enabled.

## Implemented architecture

FastAPI modular monolith, Jinja, bundled IBM Plex, vanilla JS SSE/polling, SQLite
WAL, SQLAlchemy, ten explicit Alembic migrations. The README's HTMX description
is aspirational; actual live updates are vanilla JS (ADR 0006).

| Capability | Evidence and actual boundary |
|---|---|
| Candidate profile | CRUD/import/export, verified/unverified items, user-confirmed authorization. Matching and document content filter verified items. |
| Discovery | Greenhouse/Lever/Ashby public ATS adapters; configured board list, not web-wide job search. Network separate from parser/persistence; bounded requests, rate limits, source histories and deduplication. |
| Matching | Deterministic versioned filters and weighted scores, unknown eligibility, persistent overrides. No learned or model-based ranking. |
| Research | Extract posting statements; capture/review evidence; official accepted evidence informs policy. No autonomous company investigation. |
| Documents | Verified claim maps, QA, immutable content versions, generic DOCX renderer. **Exact master resume format preservation is absent.** |
| Applications | Workspace, statuses, approval snapshots, expiry, hashes and manual record-of-action. No submission capability. |
| Outreach | User-entered contacts and draft-only messages with approval gate. No recruiter discovery or sending. |
| Analytics | Funnel, cohorts, Wilson intervals and conservative recommendations. No autonomous strategy optimizer. |
| Models | Disabled/Ollama only, one schema-validating gateway, cache and usage metadata. Optional job summaries; no model is required for core workflows. |
| Operations | Durable queue, claim leases, backoff/dead letters, worker and interval scheduling, activity stream, backups and restore verification. No persistent named agent graph or handoff/attempt history. |
| Market intelligence / interviews | Not implemented. No niche-role intelligence or personalized interview coach. |

## First vertical slice design

Add `db/models/agents.py` and migration `0011` for missions, agent runs and
attempts. Add `modules/agents/` for a fixed, versioned dependency graph with
bounded tools. Reuse the existing worker and task queue; handoffs and successful
completion commit atomically. Add `/mission-control` and a live fragment, run
history/detail pages, CSRF-protected start/retry forms and honest empty/error
states. Keep `/` and all existing workflows available.

Executable path: public-source discovery -> verified-profile matching -> posting
evidence research for shortlisted jobs -> analytics snapshot -> operational
verification. These are deterministic specialist agents; local AI remains optional
and is not presented as autonomous reasoning. Persist summaries/counts and links,
not prompts, resume text or authorization answers.

## Risks and staged decisions

- SQLite worker ownership needs fencing and lease renewal for long-running work;
  task completion must not be accepted from an expired owner.
- Discovery may partially fail. Surface degraded results and stop on total failure;
  do not label a failed feed as successful intelligence.
- Handlers must tolerate replay after crashes. Existing ingestion, score hashes and
  research lookup provide idempotence. This is at-least-once execution.
- Local UI has CSRF and CSP but no authentication: retain loopback binding.
- Master resume support needs explicit template import, allowed-edit regions and
  visual regression checks before format-preservation can be claimed.
- Later stages: master resume fidelity, market/recruiter intelligence with source
  provenance, interview coaching, optional Ollama augmentation and quality gates.
  None of these is simulated as complete in the first slice.
- No live sources are contacted during automated validation; public access terms
  still need review for each configured source in actual use.

## Proposed sequence

1. Audit and baseline (this commit).
2. Durable orchestration, dependency handoffs, retries and meaningful integration tests.
3. Mission Control UI, live updates, migration preservation checks and usage docs.
4. Full regression/lint/types; produce a review patch and an exact validation report.
