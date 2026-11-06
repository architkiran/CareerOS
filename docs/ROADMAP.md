# Implementation roadmap

Build in vertical slices. Every phase must leave a runnable application.

## Phase 0: repository and engineering foundation
- inspect repo; preserve existing work;
- create pyproject, settings, logging, app entry point;
- SQLite connection, SQLAlchemy base, Alembic;
- health endpoint and basic dashboard shell;
- pytest, Ruff, CI optional;
- `.gitignore` for data, exports, env, caches.

Acceptance: app starts locally, health endpoint works, migration applies, tests pass.

## Phase 1: candidate profile and role lanes
- profile CRUD;
- verified facts, skills, experience, projects;
- multiple role lanes and configurable preferences;
- work authorization fields entered by user;
- import/export profile JSON.

Acceptance: user can edit profile and distinguish verified from unverified facts.

## Phase 2: source ingestion
- source registry;
- Greenhouse adapter;
- Lever adapter;
- Ashby adapter;
- configured company watchlist;
- normalized job schema;
- source run records, retries, rate limits;
- idempotent ingestion and deduplication.

Acceptance: ingest fixture jobs and selected live public feeds; repeated run creates no duplicates; failures are isolated and visible.

## Phase 3: job inbox and live operations dashboard
- jobs table/detail pages;
- filters and search;
- pipeline run controls;
- task queue and worker;
- activity event stream;
- SSE + polling fallback;
- empty/loading/error states.

Acceptance: dashboard shows jobs arriving and pipeline events without refreshing the whole page.

## Phase 4: deterministic matching
- role lane classification;
- hard filter engine with pass/fail/unknown;
- weighted score and breakdown;
- explanations, matched/missing skills;
- user overrides with reason.

Acceptance: same input/profile/version yields same score; all score dimensions are visible and testable.

## Phase 5: employer research and work-authorization evidence
- research queue for shortlisted jobs;
- evidence records and source links;
- confidence and review status;
- unknown-state handling.

Acceptance: no unsupported sponsorship claim appears as fact; user can see evidence age/source.

## Phase 6: application workspace and document generation
- resume templates by lane;
- fact retrieval and claim map;
- DOCX generation;
- document versions and diff;
- QA checks;
- application tracker.

Acceptance: generated documents contain only supported facts; warnings block approval until resolved.

## Phase 7: approvals, outreach drafts, follow-ups
- immutable approval snapshots and payload hashes;
- manual submission package;
- outreach draft only;
- follow-up reminders;
- audit trail.

Acceptance: no external action can occur without exact, current approval. MVP action remains user-submitted.

## Phase 8: analytics and learning
- funnel metrics;
- cohort-based response rates;
- role/source/resume comparisons;
- cautious recommendations with sample size.

Acceptance: metrics are traceable to application events and avoid overclaiming from small samples.

## Phase 9: optional local AI and remote deployment
- model gateway interface;
- optional Ollama adapter;
- prompt/version/cache/usage tracking;
- remote access threat review;
- backup/restore verification.

Acceptance: all core flows work with model gateway disabled and with zero spend.

## Explicitly deferred
- auto-submit;
- auto-send outreach;
- LinkedIn automation;
- unconstrained multi-agent swarm (bounded CareerOS 2.0 missions are implemented separately);
- vector DB;
- paid API dependencies;
- multi-user SaaS;
- mobile app;
- Kubernetes/microservices.


## CareerOS 2.0 staged extension

- Audit: existing 476-test baseline and actual capability assessment recorded.
- Foundation: five bounded specialists coordinated through durable missions,
  persisted dependency edges, attempts, queue leases and recoverable handoffs.
- Mission Control: persisted progress, results, errors, approvals, opportunity
  summaries, history, agent workspaces and dark/light presentation.
- Next: evidence-backed market intelligence and role suggestions, followed by
  permitted discovery coverage/freshness improvements and master DOCX fidelity.
- Later: application preparation coordination, recruiter intelligence, interview
  practice and measured strategy feedback.

See `AGENT_ORCHESTRATION.md` for exact implemented behavior and remaining limits.
