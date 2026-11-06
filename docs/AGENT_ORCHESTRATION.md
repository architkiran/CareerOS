# Bounded agent orchestration

## Working scope

The first slice uses deterministic specialist agents, not autonomous LLM dialogue.
It runs without Ollama, API keys, new services or a frontend build tool.

The fixed version-1 graph is:

`Discovery → Matching → Posting-evidence research → Analytics → Verification`

Each tool is selected by a code-owned agent key. Job text cannot name tools,
change dependencies, request additional privileges or decide approvals.
`AgentOutput` validates the summary, numeric metrics and warning list before a
step can succeed. Aggregate results never contain full candidate/resume text.

| Agent | Reads / writes | Boundary |
|---|---|---|
| Discovery | Configured ATS feeds; jobs, provenance and source runs | Existing three adapters and HTTP policies; no login, arbitrary browsing or paid source |
| Matching | Verified candidate facts, lanes and jobs; scores | Existing deterministic eligibility and scoring, including unknowns and overrides |
| Research | Active shortlisted postings; research items and pending evidence | Extracts statements only; never accepts evidence or asserts unsupported sponsorship |
| Analytics | Application events and job state; aggregate run snapshot | Existing funnel and sample-aware methods; no automatic strategy changes |
| Verification | Profile readiness, source errors, approval counts | Operational check; not a claim that all documents, permissions or external data were independently verified |

## Persistence and state

Migration `0011` only adds tables and indexes. It does not delete or recreate prior
tables. Tests compare existing user rows before/after upgrade, downgrade and re-upgrade.

- `mission`: workflow/version/trigger, lifecycle and timestamps. A partial unique
  index permits one queued/running/paused career review at a time.
- `agent_run`: one specialist step per mission, task reference, result, error and times.
- `agent_dependency`: persisted upstream edges. A step is queued only after every
  dependency succeeds. Success, queue completion, result and next handoff share
  one transaction.
- `agent_attempt`: append-preserved attempt records, including failed or interrupted
  attempts. Manual retries reset the task's retry allowance but retain this history.

A mission is queued, running, paused, cancelled, failed, succeeded or degraded.
A run is blocked, queued, running, retrying, failed, succeeded or cancelled.
A completed review with warnings is degraded, not green. No configured sources is
an actionable setup warning; all attempted feeds failing is a retryable failure;
some failing is a partial result with warnings. Downstream work is blocked on failure.

No-op SQLite writes deliberately establish a real transaction before savepoints.
This prevents legacy sqlite3 savepoint behavior from leaving a committed, partial
mission after an outer rollback. Concurrent starts and rollback are tested.

## Worker recovery and concurrency

The existing worker executes one task at a time per worker process. Conditional
claims prevent two current owners of one task. A heartbeat renews its 600-second
lease every 30 seconds; final writes are fenced by worker ID, claim attempt and
unexpired lease. A reclaimed task closes the earlier run attempt as interrupted.
Expired workers cannot publish a successful completion or enqueue downstream steps.

Execution is **at least once**: a process can crash after a service committed its
work but before task completion. Ingestion dedupe, score input hashes and existing
research lookup make replay safe for ordinary crash recovery. Fencing does not
roll back service writes already committed before a lease was lost. This is not an
exactly-once distributed execution system. Multiple worker processes should be used
cautiously: source rate limits are still local to each fetcher, not globally shared.

Automatic failures use the existing three-attempt exponential backoff policy.
Repeated abandoned leases eventually dead-letter without running the handler again.
A dead step may be manually retried only when no other career review is active.
The legacy task-retry endpoint uses the same mission recovery gate for agent tasks.

Pause and cancel stop new steps; they do not kill Python threads or undo persisted
results. Cancellation of a claimed step records completion as cancelled and never
hands off. HTTP requests keep existing bounded timeouts, retry/page/response caps.
There is **no hard process-level timeout** for arbitrary Python code in this slice.

## Interface and operation

- `/mission-control`: live persisted progress, five specialists, recent opportunities,
  action center, queue/source state, worker heartbeat, usage, backup timestamp and activity.
- `/missions/{id}`: dependency links, output metrics, warnings, attempts and recovery controls.
- `/agents`: actual executable capabilities and clearly labelled planned capabilities.
- `/agents/{key}`: allowed tools, dependency description and latest 30 runs.
- `/partials/mission-control`: autoescaped fragment, refreshed every five seconds with
  non-overlapping fetches, timeout/error state and focus protection. Existing SSE feed remains.

CSRF protects all mutations; templates autoescape source content; scripts/styles are
local under the existing strict CSP. Pages use `Cache-Control: no-store`. No external
side-effect tools are exposed. Keep the unauthenticated app bound to loopback.

The heartbeat reports when a worker was observed, not a guarantee of current liveness.
Ollama is shown as configured/disabled, not declared healthy without a connection test.
The latest backup timestamp does not imply a fresh integrity verification on every poll.
History is bounded to 20 missions on the dashboard; individual mission URLs stay available.
Mission detail is refreshed manually. Current product gaps are labelled, not simulated.

## Scheduling

Set `MISSION_SCHEDULER_ENABLED=true` for the full workflow and keep the legacy
`SCHEDULER_ENABLED=false` unless independent discovery-only runs are intentional.
`SCHEDULE_INTERVAL_HOURS` accepts 0.25–168 hours. Optional source-specific minimum gaps are configured
on Sources; they limit scheduled refresh frequency rather than creating independent clocks.
The persisted last-enqueued tick survives restarts; missed intervals coalesce into
one review. A paused or active mission is reused instead of creating duplicates.
A local machine that is asleep or shut down does not execute scheduled work.

## Next milestone

Add market research with a small, explicit permitted-source list, source dates,
confidence and evidence-backed transferable-role suggestions. Resume-template work
must separately add editable master import, allowed edit regions and rendered
layout comparisons before making an exact-format preservation claim.


## Version 2: career intelligence

New missions add an evidence-backed market step between matching and research.
The registry supports both version 1 and version 2; persisted version-1 edges
continue unchanged. Market reports use only configured public-feed postings and
verified skills. Full details and limits are in `MARKET_INTELLIGENCE.md`.

## Discovery cadence and cancellation

The global schedule now accepts 0.25–168 hours, supporting 15/30-minute and longer
cadences. Optional source-specific minimum gaps (15–10,080 minutes) are editable
on Sources and stored in source configuration. They apply to scheduled missions;
manual runs remain explicit requests and still honor HTTP rate limits. A source
minimum gap never creates a schedule faster than the global review interval.

A scheduled discovery task freezes its due-source IDs when it is queued, so retries
keep the same scope. Sources with a recent attempt are not selected merely because
the last attempt failed. A no-feeds-due result is distinct from no enabled sources.
Cancellation is checked between source requests, so a cancelled mission does not
continue fetching the rest of the company list. In-flight requests keep their
bounded timeout and results already saved remain preserved.
