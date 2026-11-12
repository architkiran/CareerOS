# CareerOS

CareerOS finds and organizes relevant jobs so you can inspect the original posting
and apply yourself. The main screens are **New Jobs, Saved Jobs, Applications**.
Everything else is optional under **Advanced / Settings**. The stack and private
data remain local; discovery and matching require no model or paid API.

For the existing Mac workspace:

```bash
zsh "/Users/architkiran/Desktop/PersonalProjects/CareerOS/Start CareerOS.command"
```

Open [Today](http://127.0.0.1:8766/today). Keep the terminal running.
The launcher checks for an existing server and never starts a second worker.
Fresh clones can use the setup instructions below (CLI default port 8000).

Current state and next steps: [PROJECT_STATUS.md](PROJECT_STATUS.md).

## Career OS 2.0 quick start (discovery and eligibility)

```bash
./Run\ Discovery.command          # fast pass: community list + Greenhouse/Lever/Ashby
./Run\ Discovery.command all      # also ~120 Workday career sites (slow first run)
careeros lca import ~/Downloads/LCA_Disclosure_Data_FY2026_Q3.xlsx --fiscal-year 2026
careeros discover --no-fetch      # re-evaluate stored jobs after a rule or evidence change
```

Then start CareerOS and open **Today** (`/today`): eligible roles, the sponsorship research
queue, and roles needing review, each with its checklist, evidence and original posting link.
Read `MISSION.md`, `PROJECT_STATUS.md`, `docs/ELIGIBILITY_RULES.md`,
`docs/SPONSORSHIP_EVIDENCE.md` and `docs/SOURCE_CATALOG.md`.

## Non-negotiable principles

1. **$0-first:** Core workflows must work without paid APIs, paid hosting, Redis, or paid data providers.
2. **Human approval:** Never submit an application, send an email/message, or make an external commitment without explicit approval for that exact action.
3. **Truthfulness:** Never invent skills, dates, metrics, responsibilities, eligibility, or sponsorship facts.
4. **Source traceability:** Every job and every material eligibility claim must retain its source URL, retrieval time, and evidence.
5. **Explainability:** Show why a job passed/failed filters and how its score was calculated.
6. **Respect access rules:** Use public ATS feeds, official career pages, permitted APIs, and user-assisted workflows. Do not bypass CAPTCHAs, authentication, rate limits, or site terms.
7. **Portable:** Local development and operation first; cloud deployment is an optional later deployment target, not a prerequisite.

## Daily workflow

1. **New Jobs:** review jobs found since your previous visit. The first visit shows
   your existing unreviewed matches. Publication dates and first discovery are
   distinct. Open the employer/ATS page directly; public-board links are labeled
   “View source posting.” Missing URLs remain visibly unavailable.
2. **Saved Jobs:** keep a next action, review requirements, and apply on the
   original website. Choose **I applied manually** only after you have applied.
   An optional application date and notes are enough; documents and approvals
   are not prerequisites for recording your own completed action.
3. **Applications:** update outcomes and notes. Earlier unsubmitted workspaces
   remain in Advanced → Optional preparation workspaces.

Monitoring defaults to every 30 minutes while the app and computer are awake.
Settings → Discovery controls the interval (15–1440 minutes) and pause state.
Each provider's stricter minimum still applies, including manual refreshes.
A saved pause preference is respected. No LinkedIn/Handshake session scraping,
automatic applications, or automatic messages are performed.

## Optional capabilities

Resume tailoring, PDF preview/export, cover letters, referral research, employer
evidence, interview practice, analytics and agent histories are retained. Start
resume/cover-letter tools from a saved role. The
[evidence workbench](docs/EVIDENCE_WORKBENCH.md) explains verified content editing
and master-template preservation. The free local compiler setup is
`.venv/bin/python scripts/setup_latex.py`; compilation uses cached resources.

Mission Control (`/mission-control`) and system diagnostics (`/advanced/system`)
are advanced tools, not the landing page. Existing bounded discovery missions
and the SQLite queue power monitoring; no new agents were added for this change.
Leave the legacy `SCHEDULER_ENABLED` and full-review
`MISSION_SCHEDULER_ENABLED` schedules disabled for the normal discovery workflow.
Detailed optional orchestration contracts remain in
[AGENT_ORCHESTRATION.md](docs/AGENT_ORCHESTRATION.md).

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
| 9. Backups | Done |

See `PROJECT_STATUS.md`.

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

## Optional Docker deployment

Run CareerOS in a container that starts itself and stays up whenever your Mac is on, so http://127.0.0.1:8000 always works. Discovery uses the same default 30-minute monitor and provider-specific limits.

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

**Limits, honestly:** it's live while your Mac is awake. When the Mac sleeps, the container pauses too, and New Jobs shows overdue source checks. It's reachable only from this Mac (`127.0.0.1`); don't change the port mapping, because CareerOS has no login (see `docs/REMOTE_ACCESS.md`).


## Run without Docker

```bash
careeros migrate   # creates ./data/careeros.db and applies migrations
careeros serve     # http://127.0.0.1:8000
```

`python -m careeros serve` works too. The direct CLI does not run migrations automatically; if they are pending, `/health` reports `degraded` and the dashboard tells you to run `careeros migrate`.

- New Jobs: <http://127.0.0.1:8000/new-jobs>
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

- `/` redirects to `/new-jobs`; `/saved-jobs` and `/applications` complete the main loop.
- **Refresh jobs** respects provider cooldowns and reuses queued/running discovery.
- **More filters** reveals location, work arrangement, seniority signals,
  sponsorship and discovery date. Source publication determines ordering when
  supplied; it is never inferred from first discovery.
- The full legacy inbox `/jobs`, source controls `/sources`, detailed posting
  history and `/advanced/system` remain available under advanced tools.
- Settings → Discovery configures the active monitor; it pauses during sleep.

Failed tasks retry with exponential backoff and are dead-lettered after their last attempt.

## Matching (Phase 4)

Every active job is scored for every enabled role lane. Rescoring is automatic after discovery and after profile or lane edits, and advanced diagnostics retains a manual rescore control.

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

From a saved job, expand **Optional tools** to open a preparation workspace.
Nothing is generated by saving or recording an application. Drafting remains an
explicit action.

- **Verified items only.** Every line is mapped to the profile items behind it (see *Claim map*).
- **QA checks.** These errors block a version: a line with no backing item, a number that isn't in the backing item, a leadership claim the profile doesn't make, a skill that isn't verified, or dates that contradict each other. These are warnings you acknowledge: missing or future dates, and unverified items that were left out.
- **Versions are immutable.** Regenerating creates a new version with a diff. Master-template PDF export and legacy Word export remain available; downloads verify stored hashes. Resume downloads retain `Archit_Kiran_Kumar_Resume.pdf`.
- **Tracker.** `/applications` lists recorded applications. Unsubmitted preparation work remains at `/applications?view=preparation`. Outcomes are entered by you. Manual recording requires your confirmation, not a document approval.

## Approvals, outreach and follow-ups (Phase 7)

**CareerOS never submits an application or sends a message.** The optional
prepared-package workflow retains its existing approval gate. This gate does not
block recording an application you independently completed:

1. Once a resume is *ready*, click **Review package and request approval** on the application. CareerOS saves an exact snapshot (destination, document versions and their hashes) with a hash of its own.
2. On the approval page, check the package, tick the confirmation and **Approve**.
3. Submit it yourself on the official posting, then click **Record it**. Only then is the application marked *submitted*, and a follow-up is scheduled for a week later.

Approvals expire after 72 hours and can be used once. They're cancelled automatically if anything in the package changes, such as a regenerated resume or an edited message. `/approvals` keeps a full audit trail.

**Outreach** is draft-only: add a contact and a message on the application, approve it, send it yourself, and record it. There's no LinkedIn automation. **Follow-ups** (`/follow-ups`) show what's due or overdue, and remain secondary to the main inbox.

## Analytics (Phase 8)

`/analytics` shows:
- the funnel from discovered to offer
- median days to submit and to first response
- response and interview rates by lane, source and submission week
- why you rejected jobs

Every rate shows its count and a 95% range. Groups with fewer than 10 applications are marked *small sample*. A recommendation only appears when two groups each have enough data and their ranges don't overlap; otherwise it says there isn't enough data yet.

## AI, backups and remote access (Phase 9)

- **AI is off by default** and nothing depends on it. All model calls go through one gateway with $0 budget caps, a cache, timeouts and a usage log. Job text is fenced as untrusted, and replies must match a strict schema.
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
| `src/careeros/modules/backup/` | Verified backup and safe restore |
| `src/careeros/web/routes/events.py` | SSE stream and polling feed |
| `src/careeros/web/static/app.js` | Live feed client (ADR 0006) |
| `tests/` | Unit and integration tests (recorded fixtures in `tests/fixtures/sources/`) |

Data lives in `./data` and generated files in `./exports`; both are created with owner-only permissions and are gitignored.

## Role-specific resume references and safe workspace copies

`/resumes` keeps original PDF variants separate from verified profile claims and
from generated application packages. References are immutable, hash-checked on
download, stored in private folders and included in backups. Their review notes
explain unresolved metrics and editable-source limitations. Registering a PDF
never marks its claims verified or changes an employment title.

`modules.backup.workspace.clone_workspace` provides a read-only SQLite snapshot,
a verified backup, restoration into a new destination, explicit migration and
private-artifact path rebasing (including an explicitly provided legacy Docker
storage alias). It refuses an existing destination and never changes the source.
Copied pending work is cancelled in the copy to avoid replaying another worker's
actions. The source's historical records and confirmed verification labels remain.


Scheduled discovery can run every 15 minutes or longer using
`SCHEDULE_INTERVAL_HOURS` (0.25 means 15 minutes). Each source's **Refresh policy**
can set a longer minimum gap and request delay. The Sources page also distinguishes
configured feeds from target employers that still need official careers-page
research. Preferred-company labels never verify sponsorship. Scheduling remains
off until explicitly enabled.


## Interview practice

Use **Prepare interview practice** on a job, or open `/interviews`. The on-demand
specialist prepares posting-specific questions and verified-project discussion
prompts, with private answers, checklists and self-assessed confidence. It runs
through durable missions and links to the exact saved plan. No answer becomes a
verified profile fact, no application status changes, and nothing is sent out.
See [interview practice behavior and limits](docs/INTERVIEW_PRACTICE.md).
