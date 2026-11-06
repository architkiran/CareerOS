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

## CareerOS 2.0: first operational slice

**Mission Control** is available at `/mission-control`; the existing Overview stays at `/`.
Run a career review to coordinate five real, deterministic specialists: discovery,
matching, posting-evidence research, analytics and verification. Results come from
persisted work, not demo data. `/agents` lists capabilities and gaps; each agent has
its own history and permission description. Mission detail shows dependency links,
results, warnings, retry timing and every execution attempt.

- Missions and agent runs persist in SQLite (migration `0011`). Completion and
  downstream handoff commit together. Duplicate start requests reuse the active mission.
- Pause/resume/cancel apply between steps. An in-flight step may finish and already
  persisted results remain available. Failed steps retry with backoff up to three
  times, then require manual retry. Manual retries preserve the previous attempts.
- Worker leases renew every 30 seconds. Completion is fenced by owner and claim
  attempt; interrupted work can be reclaimed after its 10-minute lease expires.
- The dark-first interface has a saved light-mode option, keyboard focus states,
  responsive layouts and same-origin live polling every five seconds.
- No paid services or AI are required. There are no send, submit, approval-decision
  or profile-edit tools in the agent executor. Existing approval gates remain human-operated.

To schedule the full review, set `MISSION_SCHEDULER_ENABLED=true` and
`SCHEDULE_INTERVAL_HOURS=24` in `.env`. Keep `SCHEDULER_ENABLED=false` to avoid also
running the legacy discovery-only schedule. Both are disabled by default outside
Docker; Docker currently enables its legacy discovery schedule by default, so set
it explicitly to false when enabling mission scheduling. Local scheduling needs a
running worker and pauses while your Mac sleeps. A paused mission blocks another
career review until resumed or cancelled.

The audit, implementation limits and next stages are in
[the CareerOS 2.0 audit](docs/CAREEROS_2_AUDIT.md) and
[orchestration architecture](docs/AGENT_ORCHESTRATION.md).
This slice does not implement market intelligence, interview coaching or exact
master-resume template preservation. Existing generic document generation remains
available, with its verified-fact and QA gates.

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
| 3. Job inbox, task queue, live dashboard | Done |
| 4. Deterministic matching | Done |
| 5. Employer research and work-authorization evidence | Done |
| 6. Application workspace and document generation | Done |
| 7. Approvals, outreach drafts, follow-ups | Done |
| 8. Analytics | Done |
| 9. Model gateway, optional local AI, backups | Done |

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

## Always-on with Docker (recommended)

Run CareerOS in a container that starts itself and stays up whenever your Mac is on, so http://127.0.0.1:8000 always works. Discovery also runs once a day on its own.

**One-time setup**
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free for personal use).
2. In Docker Desktop: **Settings → General → Start Docker Desktop when you sign in**.
3. Stop any `careeros serve` running in a terminal, then from this folder:
   ```bash
   docker compose up -d --build
   ```
4. Bookmark http://127.0.0.1:8000.

That's it. The container restarts by itself after crashes, reboots and Docker Desktop restarts (`restart: unless-stopped`). It uses this folder's `data/`, `exports/`, `backups/` and `config/`, so your existing database carries over.

**What it does on start:** if your database needs migrations, it first writes a verified backup to `backups/`, then migrates. A new database is created if none exists.

**Choosing companies:** edit `config/sources.toml` (start from `config/sources.example.toml`, which lists 17 verified fintech and Boston-area boards) and run `docker compose up -d`. On every start the container adds new sources and disables any marked `enabled = false`. It never re-enables a source you turned off in the dashboard.

**Everyday commands** (run CareerOS commands *inside* the container, never `careeros` on the Mac at the same time):
```bash
docker compose exec careeros careeros sources sync     # after editing config/sources.toml
docker compose exec careeros careeros backup
docker compose logs -f careeros                         # see what it's doing
docker compose up -d --build                            # after pulling new code
docker compose down                                     # stop it (it won't come back until `up`)
```

**Limits, honestly:** it's live while your Mac is awake. When the Mac sleeps, the container pauses too, and the Overview shows a missed scheduled run. It's reachable only from this Mac (`127.0.0.1`); don't change the port mapping, because CareerOS has no login (see `docs/REMOTE_ACCESS.md`).

**Optional local AI in Docker:** set `MODEL_PROVIDER=ollama` and `OLLAMA_MODEL=...` in `.env`; the container reaches Ollama on your Mac at `host.docker.internal:11434`.

## Run without Docker

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

## Dashboard and background work (Phase 3)

`careeros serve` runs the dashboard **and** a background worker in one process. Use `careeros serve --no-worker` plus `careeros worker` if you want them separate.

- **Overview** (`/`): new jobs today, active and shortlisted counts, possible duplicates, last discovery run, source health, task queue depth, failed tasks with a *Retry* button, and a live activity feed (Server-Sent Events, with a polling fallback).
- **Run discovery now** queues a run; clicking twice doesn't queue twice. Each source also has *Run now* on `/sources`.
- **Job inbox** (`/jobs`): search and filter by triage state, source, workplace, date, active/closed, and possible duplicates. Rejected jobs are hidden unless you filter for them.
- **Job detail**: every source sighting with links, salary only when disclosed, plain-text description, duplicate group, and triage (shortlist, save, mark reviewed, reject with a required reason, reset).
- **Schedule**: set `SCHEDULER_ENABLED=true` (and optionally `SCHEDULE_INTERVAL_HOURS`) in `.env`. When the Mac sleeps, runs pause; the Overview says so when a run is overdue instead of pretending.

Failed tasks retry with exponential backoff and are dead-lettered after their last attempt.

## Matching (Phase 4)

Every active job is scored for every enabled role lane. Rescoring is automatic after discovery and after profile or lane edits, and there's a *Rescore* button on the Overview.

- **Hard filters** return pass, fail or unknown with a reason and evidence: posting still listed, employment type, excluded title terms, lane exclusions, inferred seniority, location vs your preferences, and what the posting says about sponsorship compared with your *confirmed* work-authorization answers. Unknown is shown for review, never silently passed or failed.
- **Score (0-100)** uses the lane's seven weights. Missing information (for example undisclosed salary) counts as neutral, and each score shows how complete its information was.
- **Only verified profile items** count toward skills and experience.
- **Overrides**: on a job's page you can override eligibility or score for a lane, with a reason. Overrides survive rescoring.
- The inbox hides filtered-out jobs by default and can filter by lane, eligibility and minimum score, or sort by best score.

Details and rationale: `docs/adr/0007-deterministic-matching-v1.md`.

## Employer research (Phase 5)

Shortlisting a job opens research for it (or click *Start research* on any job). CareerOS scans the posting for sponsorship or citizenship statements and adds each as quoted evidence for you to review. Add your own evidence from the company's careers or immigration page with a link, date, source type and confidence.

- Only **accepted** evidence from the posting, the company's own pages, or government data sets the employer policy (*Sponsorship offered*, *No sponsorship*, *Case by case*, or *Unknown*). Third-party sites are shown as leads.
- Job-specific evidence beats company-wide evidence; conflicting accepted evidence leaves the policy unknown and says so; evidence older than six months is flagged.
- When a posting is silent, matching uses this policy, so research turns "needs review" into a real pass or fail.
- `/research` lists everything in progress. CareerOS gives no legal advice; application answers about authorization always come from you.

## Applications and documents (Phase 6)

On any job, click **Start application**. The workspace (`/applications/<id>`) generates a resume and a cover letter from templates for the job's best lane. No AI is involved.

- **Verified items only.** Every line is mapped to the profile items behind it (see *Claim map*).
- **QA checks.** These errors block a version: a line with no backing item, a number that isn't in the backing item, a leadership claim the profile doesn't make, a skill that isn't verified, or dates that contradict each other. These are warnings you acknowledge: missing or future dates, and unverified items that were left out.
- **Versions are immutable.** Regenerating after a profile change creates v2, v3 and so on, with a diff. Files are `.docx` in `data/documents/` (owner-only permissions), each checked against its stored hash on download.
- **Tracker.** `/applications` lists everything. Statuses after submission (response, screen, interview, offer, rejected, withdrawn) are set by you. *Submitted* is only recorded through the approval step (Phase 7).

## Approvals, outreach and follow-ups (Phase 7)

**CareerOS never submits an application or sends a message.** Every external action goes through one approval gate:

1. Once a resume is *ready*, click **Review package and request approval** on the application. CareerOS saves an exact snapshot (destination, document versions and their hashes) with a hash of its own.
2. On the approval page, check the package, tick the confirmation and **Approve**.
3. Submit it yourself on the official posting, then click **Record it**. Only then is the application marked *submitted*, and a follow-up is scheduled for a week later.

Approvals expire after 72 hours and can be used once. They're cancelled automatically if anything in the package changes, such as a regenerated resume or an edited message. `/approvals` keeps a full audit trail.

**Outreach** is draft-only: add a contact and a message on the application, approve it, send it yourself, and record it. There's no LinkedIn automation. **Follow-ups** (`/follow-ups`) show what's due or overdue, and the Overview counts them.

## Analytics (Phase 8)

`/analytics` shows:
- the funnel from discovered to offer
- median days to submit and to first response
- response and interview rates by lane, source and submission week
- why you rejected jobs

Every rate shows its count and a 95% range. Groups with fewer than 10 applications are marked *small sample*. A recommendation only appears when two groups each have enough data and their ranges don't overlap; otherwise it says there isn't enough data yet.

## AI, backups and remote access (Phase 9)

- **AI is off by default** and nothing depends on it. All model calls go through one gateway with $0 budget caps, a cache, timeouts and a usage log. Job text is fenced as untrusted, and replies must match a strict schema.
- **Optional local model:** install [Ollama](https://ollama.com), pull a small model, then set `MODEL_PROVIDER=ollama` and `OLLAMA_MODEL=<name>` in `.env`. You'll get a *Summarise with local model* button on job pages. Summaries are labelled as possibly wrong and are never used for filters, scores or documents. `/settings` shows status and usage, and has a connection test.
- **Backups:** `careeros backup` writes a verified `.tar.gz` (consistent database copy plus your documents, with SHA-256 hashes) to `./backups`. `careeros backup --verify FILE` checks an archive. `careeros restore FILE --yes` restores one after verifying it, and your current data is moved aside, not deleted. Keep copies on a drive you own.
- **Remote access:** `careeros serve` refuses to listen on anything except localhost unless `ALLOW_REMOTE=true`. Read `docs/REMOTE_ACCESS.md` first.

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
| `src/careeros/modules/scheduler/queue.py` | SQLite task queue: leases, idempotency keys, backoff, dead-lettering |
| `src/careeros/modules/scheduler/worker.py` | Task handlers, local scheduler, worker thread |
| `src/careeros/modules/jobs/service.py` | Inbox queries, job detail, triage |
| `src/careeros/modules/matching/` | Seniority inference, hard filters, scoring (pure functions), persistence and overrides (migration `0005`) |
| `src/careeros/modules/research/` | Evidence capture, review and employer policy (migration `0007`) |
| `src/careeros/modules/documents/` | Content builder, QA checks, DOCX rendering, versions and diff (migration `0008`) |
| `src/careeros/modules/applications/` | Application tracker and status rules |
| `src/careeros/modules/approvals/` | Approval gate, payload snapshots and hashes, follow-ups (migration `0009`) |
| `src/careeros/modules/outreach/` | Draft-only outreach contacts and messages |
| `src/careeros/modules/analytics/` | Funnel, conversion rates with Wilson intervals, cautious recommendations |
| `src/careeros/modules/models/gateway.py` | Model gateway, Ollama adapter, usage and cache (migration `0010`) |
| `src/careeros/modules/backup/` | Verified backup and safe restore |
| `src/careeros/web/routes/events.py` | SSE stream and polling feed |
| `src/careeros/web/static/app.js` | Live feed client (ADR 0006) |
| `tests/` | Unit and integration tests (recorded fixtures in `tests/fixtures/sources/`) |

Data lives in `./data` and generated files in `./exports`; both are created with owner-only permissions and are gitignored.
