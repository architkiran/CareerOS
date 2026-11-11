# ADR 0009: Career OS 2.0 is an incremental replacement, not a rewrite

Date: 2026-11-11. Status: accepted. Full audit: `docs/AUDIT_2026-11-11.md`.

## Problem

After a week of operation the existing system held 7,062 postings and produced 8 passing
role-lane matches out of 56,496, no Level-B sponsorship evidence, and no submitted
application. The mission brief permits a full rebuild. Should we?

## Options considered

1. **Rebuild** on Next.js + FastAPI + PostgreSQL + a workflow engine (LangGraph / Temporal).
2. **Keep everything** and tune the lane rules.
3. **Incremental replacement**: keep the sound core, replace the parts that caused the
   failure, retire the parts that do not serve employment.

## Decision: option 3

The failure was not engineering quality. The code is typed, migrated and covered by 765
passing tests. The failure was **what the system looked at and how it judged it**:

- 27 sources, 19 of them late-stage fintech and infrastructure companies on Greenhouse, which
  post few entry-level analyst roles. None of the candidate's Tier-1 targets was reachable,
  because they use Workday and there was no Workday adapter.
- Eligibility was computed per job *per role lane* (8 lanes × 7,062 jobs), so the same job
  failed seven lanes and the candidate saw lane noise instead of one verdict.
- Sponsorship relied on posting text alone. With no employer-level evidence, 73% of jobs sat
  at "not indicated" and nothing could be prioritized.

So 2.0 keeps the modular monolith, SQLAlchemy/Alembic, the fetcher, the ingestion and dedupe
pipeline, provenance model, approval gates and application records, and adds:

- a **Workday adapter** and a **community new-graduate feed adapter**;
- a **harvester** that derives official ATS boards from real posting URLs (27 → 220 boards);
- a **sponsorship evidence engine** with levels A/B/C/D/U and DOL LCA import;
- a **lane-independent eligibility engine** producing one verdict per job;
- a **Today** page and a `careeros discover` command that writes a daily digest.

## Technology choices, each evaluated against the brief's suggestions

| Suggestion | Decision | Why |
|---|---|---|
| PostgreSQL / pgvector | Stay on SQLite (WAL) | One user, one machine, under 1 GB. Postgres adds a service to run and nothing to the job search. Revisit only if the app is hosted. |
| LangGraph / Temporal / Celery+Redis | Keep the existing DB-backed queue | Hard rules are deterministic by requirement; there is no multi-agent workflow on the critical path that needs a durable graph engine. |
| Agent fleet | No agents on the discovery path | Parsing, dedupe, eligibility and evidence levels are code with tests. Language models are reserved for synthesis (tailoring, outreach drafts, interview prep), where they add value. |
| Next.js + shadcn + Framer Motion | Deferred, not rejected | The server-rendered UI already has a coherent design system. A frontend rewrite before discovery works would spend the limited build window on polish. Planned once phases 1 and 2 are proven. |
| Playwright | Not used | Every source so far has a public JSON endpoint. |

## Trade-offs

- The old lane matcher and the new verdict engine coexist for now (New Jobs uses the former,
  Today the latter). The lane matcher is scheduled for removal once Today has been used for a
  week without regressions.
- Workday and community sources are partial snapshots, so closure for those jobs is inferred
  from staleness, not absence.
- Server-rendered UI limits interaction richness until the frontend decision is revisited.

## Migration impact

Additive only: migration 0018 creates `job_verdict` and `employer_lca_stat`. No existing table
or row is changed. Existing data, backups and the three core screens keep working.

## Cost

Zero. No paid API, service or host. One new free dependency (openpyxl) for reading DOL files.
