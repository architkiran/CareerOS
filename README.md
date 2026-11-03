# CareerOS

A local-first, cost-minimal personal career operating system. CareerOS discovers relevant full-time jobs, explains fit, tracks evidence and work-authorization uncertainty, prepares truthful application materials, and routes every external action through a human approval gate.

## Non-negotiable principles

1. **$0-first:** Core workflows must work without paid APIs, paid hosting, Redis, or paid data providers.
2. **Human approval:** Never submit an application, send an email/message, or make an external commitment without explicit approval for that exact action.
3. **Truthfulness:** Never invent skills, dates, metrics, responsibilities, eligibility, or sponsorship facts.
4. **Source traceability:** Every job and every material eligibility claim must retain its source URL, retrieval time, and evidence.
5. **Explainability:** Show why a job passed/failed filters and how its score was calculated.
6. **Respect access rules:** Use public ATS feeds, official career pages, permitted APIs, and user-assisted workflows. Do not bypass CAPTCHAs, authentication, rate limits, or site terms.
7. **Portable:** Local development and operation first; cloud deployment is an optional later deployment target, not a prerequisite.

## First run

Read `CLAUDE.md` before changing anything. Then read `docs/ARCHITECTURE.md`, `docs/PRODUCT_SPEC.md`, and `docs/ROADMAP.md`.

The initial implementation should be a working vertical slice:
- create/edit a candidate profile;
- ingest public Greenhouse, Lever, and Ashby jobs from a small configured company list;
- normalize and deduplicate jobs;
- apply deterministic hard filters;
- calculate explainable fit scores;
- show jobs and pipeline events in the dashboard;
- allow the user to save, reject, or shortlist a job.

Do not start with automated form submission, browser automation, a complex agent swarm, or cloud infrastructure.

## Target user

One candidate seeking full-time roles in the United States, with possible relocation. Target families include data/business/BI analytics, financial/operations analysis, business/product analyst, product operations/associate product roles, consulting, and selected data engineering roles. Work authorization and sponsorship must be represented explicitly and verified per employer/job where possible. Never assume eligibility.

## Current technology direction

- Python 3.12+
- FastAPI
- Server-rendered Jinja templates + HTMX + minimal Alpine.js (no mandatory Node build)
- SQLite in WAL mode for MVP
- SQLAlchemy 2 + Alembic
- Pydantic settings/schemas
- APScheduler or OS scheduler for local runs
- SQLite-backed task/event tables; no Redis initially
- SSE for live dashboard updates, with polling fallback
- pytest, Ruff, mypy (gradually)
- Docker optional for reproducible deployment, not required for local use

See `docs/` for detailed contracts.

## Status

| Phase | State |
|---|---|
| 0. Engineering foundation | Done |
| 1. Candidate profile and role lanes | Done |
| 2. Source ingestion (Greenhouse, Lever, Ashby) | Done |
| 3+ | Not started |

See `docs/ROADMAP.md`.

## Setup (macOS)

Requires Python 3.12 or newer. Check with `python3 --version`.

Using [uv](https://docs.astral.sh/uv/) (recommended, free):

```bash
cd CareerOS
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env
```

Using plain pip:

```bash
cd CareerOS
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Run

```bash
careeros migrate   # creates ./data/careeros.db and applies migrations
careeros serve     # http://127.0.0.1:8000
```

`python -m careeros serve` works too. Migrations never run automatically on startup; if they are pending, `/health` reports `degraded` and the dashboard tells you to run `careeros migrate`.

- Dashboard: <http://127.0.0.1:8000/>
- Health JSON: <http://127.0.0.1:8000/health> (`ok` or `degraded` return 200; `error` returns 503)

The server binds to `127.0.0.1` only. Runtime AI is disabled and spend caps are $0.

## Test and check

```bash
pytest                 # full suite, no network
ruff check .
ruff format --check .
mypy
```

Tests use temporary SQLite files and make no network calls.

## Using the profile (Phase 1)

- **Profile** (`/profile`): basics, facts, skills, experience, projects. Every item is `verified` or `unverified`; only verified items will be used in anything that leaves the app.
- **Role lanes** (`/lanes`): click *Add default lanes* for the six target families, then edit title keywords, skills, seniority, and weights (must total 100).
- **Work authorization** (`/profile/work-authorization`): entered by you, never inferred, never written to logs or the activity feed, and excluded from exports unless you ask for it.
- **Export / import**: download your profile as JSON; importing refuses to overwrite an existing profile unless you tick *replace*.

All forms are CSRF-protected.

## Fetching jobs (Phase 2)

```bash
cp config/sources.example.toml config/sources.toml   # edit the company list
careeros sources sync                                 # add them to the database
careeros ingest                                       # fetch now (or --token <board>)
```

Each run normalizes postings, deduplicates them (same source id, then canonical URL, then company + title + location + description), keeps every source record and its raw payload, closes jobs a board no longer lists, and reopens them if they come back. `/sources` shows each source's last run, counts, and errors. A wrong board token shows as a 404; a source that returns 403/429 three times is disabled until you re-enable it.

Only explicit fields are stored: employment type and salary stay empty when the source doesn't state them.

## Code map

| Path | Purpose |
|---|---|
| `src/careeros/config.py` | Pydantic settings. Localhost default, SQLite-only, AI disabled, budgets >= 0 |
| `src/careeros/common/` | UTC clock, ID helper, logging setup |
| `src/careeros/db/session.py` | SQLite engine with WAL, foreign keys, 5s busy timeout |
| `src/careeros/db/base.py` | Declarative base, naming conventions, `UTCDateTime` (rejects naive datetimes) |
| `src/careeros/db/models/operations.py` | `activity_event` (append-only, integer id as future SSE cursor) and `setting` |
| `src/careeros/db/migrations.py` | Alembic helpers for `careeros migrate` and schema checks |
| `migrations/` | Alembic environment and revision `0001` |
| `src/careeros/modules/system/status.py` | Health checks shared by `/health` and the dashboard |
| `src/careeros/web/` | Routes, Jinja templates (autoescaped), CSS, security headers |
| `src/careeros/db/models/profile.py` | Profile, facts, skills, experience, projects, role lanes, work authorization (migration `0002`) |
| `src/careeros/modules/profile/` | Validated schemas, default lanes, profile service, export/import |
| `src/careeros/modules/events/` | Activity event recording (no sensitive values) |
| `src/careeros/web/csrf.py` | Double-submit CSRF protection |
| `src/careeros/db/models/jobs.py` | Company, source, source run, job, job source record (migration `0003`) |
| `src/careeros/modules/sources/http.py` | Fetcher: timeouts, retries with backoff, Retry-After, per-domain rate limit, size cap |
| `src/careeros/modules/sources/adapters/` | Greenhouse, Lever, Ashby parsers (no network or DB code) |
| `src/careeros/modules/sources/registry.py` | Source registry and TOML watchlist |
| `src/careeros/modules/ingestion/service.py` | Normalize, dedupe, persist, close/reopen, run bookkeeping |
| `config/sources.example.toml` | Example watchlist |
| `tests/` | Unit and integration tests (recorded fixtures in `tests/fixtures/sources/`) |

Data lives in `./data` and generated files in `./exports`; both are created with owner-only permissions and are gitignored.
