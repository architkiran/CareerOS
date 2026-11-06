# Architecture

## Summary

Use a **local-first modular monolith**. One Python application, one SQLite database, one worker process (or one process in development), one web dashboard. Modules have clear boundaries but share a deployable unit.

This is deliberately less fashionable than microservices. It is also dramatically cheaper and easier for one person to debug.

## High-level architecture

```text
                ┌──────────────────────────────┐
                │ Browser: CareerOS dashboard  │
                │ Jinja + HTMX + SSE           │
                └──────────────┬───────────────┘
                               │ HTTP
                ┌──────────────▼───────────────┐
                │ FastAPI application          │
                │ routes / auth / templates    │
                └──────────────┬───────────────┘
                               │
       ┌───────────────────────▼────────────────────────┐
       │                 Application layer              │
       │ profile | jobs | matching | research | docs    │
       │ approvals | applications | analytics | events │
       └──────────────┬──────────────────┬──────────────┘
                      │                  │
          ┌───────────▼────────┐  ┌──────▼─────────────┐
          │ SQLite + files     │  │ Task runner        │
          │ WAL / migrations   │  │ scheduled + queued │
          └────────────────────┘  └──────┬─────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │ Source adapters            │
                          │ Greenhouse / Lever / Ashby │
                          │ approved company pages     │
                          └─────────────┬──────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │ Normalize → dedupe →       │
                          │ filter → score → persist   │
                          └────────────────────────────┘

              Optional Model Gateway (disabled by default)
              ┌────────────────────────────────────────┐
              │ rules → local Ollama → optional API     │
              │ budget / cache / audit / timeout       │
              └────────────────────────────────────────┘
```

## Technology choices

| Concern | MVP choice | Why |
|---|---|---|
| Language | Python 3.12+ | Strong ecosystem, accessible maintenance |
| Web | FastAPI | API + server-rendered dashboard in one process |
| UI | Jinja2 + HTMX + small Alpine.js | Live-feeling UI without a React build chain |
| Database | SQLite WAL | $0, portable, enough for one user |
| ORM/migrations | SQLAlchemy 2 + Alembic | Explicit schema and safe evolution |
| Validation | Pydantic | Strong boundaries around external data |
| Scheduler | APScheduler initially; OS scheduler fallback | No external service required |
| Queue | SQLite task table with leases | Avoid Redis and hosted queues |
| Live updates | Server-Sent Events (SSE), polling fallback | Simple one-way event stream |
| Files | Local private data directory | No cloud storage bill |
| Documents | python-docx; LibreOffice optional for PDF | Local document creation |
| Testing | pytest + respx/httpx mocks | Test without live network |
| Quality | Ruff; mypy incrementally | Fast feedback |
| Packaging | uv or pip + pyproject.toml | Reproducible environment |
| Deployment | Mac local first; Docker optional | No mandatory hosting |

## Module boundaries

- `profile`: candidate facts, skills, preferences, role lanes, work authorization.
- `sources`: source adapters, fetch policies, source registry.
- `ingestion`: normalization, validation, dedupe, freshness.
- `jobs`: canonical job records and lifecycle.
- `matching`: hard filters, role classification, score breakdown.
- `research`: employer and sponsorship evidence.
- `documents`: templates, rendering, versioning, claim verification.
- `applications`: application records and status transitions.
- `approvals`: approval queue and immutable action authorization.
- `outreach`: draft-only contact/recruiter tracking.
- `scheduler`: schedules, tasks, leases, retries.
- `events`: append-only activity stream for dashboard.
- `analytics`: funnel and conversion calculations.
- `models`: optional local/API model gateway.
- `web`: routes, templates, SSE endpoint.
- `common`: config, logging, clock, IDs, errors.

Modules must not import each other's internal database models casually. Use service functions and shared schemas. Keep the MVP pragmatic; don't create a framework inside the framework.

## Repository layout

```text
careeros/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── alembic.ini
├── migrations/
├── src/careeros/
│   ├── main.py
│   ├── config.py
│   ├── db/
│   │   ├── session.py
│   │   ├── base.py
│   │   └── models/
│   ├── modules/
│   │   ├── profile/
│   │   ├── sources/
│   │   ├── ingestion/
│   │   ├── jobs/
│   │   ├── matching/
│   │   ├── research/
│   │   ├── documents/
│   │   ├── applications/
│   │   ├── approvals/
│   │   ├── outreach/
│   │   ├── scheduler/
│   │   ├── events/
│   │   ├── analytics/
│   │   └── models/
│   ├── web/
│   │   ├── routes/
│   │   ├── templates/
│   │   └── static/
│   └── workers/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── data/                 # gitignored, private local state
├── exports/              # gitignored generated documents
└── docs/
```

## Runtime modes

1. `web`: serves dashboard.
2. `worker`: claims queued tasks and executes bounded jobs.
3. `all`: convenient local development mode; web and worker can run together.

Use one SQLite database file. Enable WAL, foreign keys, and a busy timeout. Keep write transactions short. If concurrent writes become a real bottleneck, measure first and only then consider PostgreSQL.

## Task queue design

`tasks` table fields:
- id, task_type, payload_json, status;
- priority, run_after, attempts, max_attempts;
- locked_by, locked_until;
- created_at, started_at, finished_at;
- last_error, idempotency_key.

Worker claims a task in a short transaction using a lease. A crashed worker's lease expires and another worker may retry. Handlers must be idempotent. Use exponential backoff with jitter and a maximum retry count. Dead-letter exhausted tasks and surface them on the dashboard.

## Live dashboard

Write an event row for meaningful state changes:
- `run.started`, `source.fetch.completed`, `job.ingested`, `job.duplicate`,
- `job.filtered`, `job.scored`, `research.completed`,
- `document.generated`, `approval.created`, `approval.decided`,
- `application.status_changed`, `task.failed`.

SSE endpoint streams events after a cursor (`Last-Event-ID` or query cursor). Send heartbeat comments. Reconnect automatically. Polling fallback every few seconds if SSE is unavailable. Do not stream secrets or full personal documents.

## Security model

MVP is single-user and binds to `127.0.0.1` by default. If exposed on a LAN or cloud, require authentication, HTTPS, secure cookies, CSRF protection for state-changing browser actions, and a restrictive firewall. Never expose the raw SQLite file or data directory.

## Scaling path

Do not prebuild for imaginary scale. Upgrade only when measurements justify it:
- SQLite → PostgreSQL when concurrent writers, multi-device access, or data size justify it.
- SQLite task queue → Redis only if throughput/lease contention requires it.
- HTMX → React only if UI complexity justifies it.
- local model → API provider only if quality improvement is measurable and user approves cost.
- local files → encrypted object storage only if remote deployment requires it.


## CareerOS 2.0 bounded orchestration

The first extension retains this modular monolith and reuses the task queue.
`modules/agents` owns code-defined capabilities, validated output contracts and
persisted state transitions. `mission`, `agent_run`, `agent_dependency` and
`agent_attempt` extend the schema through migration 0011. Mission Control is a
server-rendered view of these tables. See `AGENT_ORCHESTRATION.md`.
