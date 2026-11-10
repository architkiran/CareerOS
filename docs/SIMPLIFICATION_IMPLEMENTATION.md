# CareerOS simplification — verified implementation

Implemented 10 November 2026 on `feat/simple-job-discovery`, based on `3c5b9db`.
The user-authored `newchanges.md` is unchanged. See the preceding
[audit](SIMPLIFICATION_AUDIT.md) for the original behavior and exact defects.

## Product loop and completed phases

| Phase | Implemented result | Main code |
|---|---|---|
| 0. Audit | Inspected existing stack, source adapters, routes, matching, scheduler, docs and tests; established a passing baseline before editing | `docs/SIMPLIFICATION_AUDIT.md` |
| 1. Trust discovery | Separate source/observation/fetch times; stable identity; material revisions/reposts; conservative multi-source closure; 30-minute default monitor with stricter provider floors | `modules/ingestion/service.py`, `modules/sources/`, migrations `0016`/`0017` |
| 2. Original/manual | Exact source URLs open directly in a new tab; employer/ATS preferred; invalid destinations unavailable; user-confirmed local manual application record, without preparation prerequisites | `modules/jobs/inbox.py`, `modules/applications/service.py`, `web/routes/inbox.py`, `web/routes/applications.py` |
| 3. Simple UI | New Jobs landing, Saved Jobs, Applications; compact cards, collapsed filters/evidence/tools; quiet Advanced; dated notes/outcomes; old preparation records preserved | `web/templates/inbox.html`, `_inbox_results.html`, `application_record.html`, `base.html`, `web/static/inbox.js` |
| 4. Match quality | Separate labeled relevance/hard gates; four sponsorship labels with dated evidence and expiry; decision metrics with honest denominators and unknowns | `modules/matching/evaluation.py`, `modules/jobs/sponsorship.py`, `modules/analytics/quality.py` |
| 5. Optional tools | Existing resume/cover-letter preparation available from a saved role; outreach/research/analytics/agents retained under Advanced; no new agents or paid services | Saved Jobs optional disclosure; existing advanced modules |

## Behavior and integrity

- `/` redirects to `/new-jobs`. The only primary navigation links are New Jobs,
  Saved Jobs and Applications. Existing deep links still work; diagnostics moved
  to `/advanced/system`.
- First visit shows existing unreviewed matches. Later visits use the previous
  visit as a cutoff. A 30-minute visit window stays stable across pagination;
  passive polls do not advance it. Review/dismiss/save affect only explicit local
  decisions. “Mark this page reviewed” includes only that displayed page.
- Source dates drive ordering when supplied and not in the future. Cards identify
  original publication, republish, source creation or public-provider reporting.
  Missing dates stay unknown; “Recently discovered” is limited to first seen
  within seven days. The discovery-date filter is not a publication-age claim.
- Sources retain their original URLs, queries and fragments. Syntax validation
  rejects dangerous/malformed destinations without rewriting them into search
  pages. Employer/ATS originals rank ahead of aggregator sightings; a public
  board destination is labeled “View source posting.” URLs are easy to copy.
- Each card shows at most three match reasons and the most important concern.
  Hard failures stay excluded even with a high keyword score. Unknown eligibility
  remains available for review. Default new lane rules allow entry/junior;
  previously saved lane rules were not rewritten or re-enabled.
- Sponsorship is Confirmed, Not supported, Uncertain or Not indicated. Accepted
  current role evidence has priority; company positives alone do not confirm an
  individual role. Stale/conflicting evidence stays uncertain, silence is not a
  negative policy, and application authorization answers still come from the user.
- Saving does not start enrichment, generate documents or create approval work.
  Optional preparation starts only on request. Existing exact-template PDF and
  editable evidence workbench capabilities were retained, not reimplemented.
- Applications lists records with an actual recorded submission date. Earlier
  preparation records remain at `/applications?view=preparation`. Recording a
  manually completed application is idempotent, explicitly confirmed, accepts an
  optional date/notes, and never sends or submits anything. Existing prepared-
  package approval gates and immutable document verification remain in place.

## Additive field map

All timestamps are UTC in storage and localized for display.

| Meaning | Storage |
|---|---|
| Publication | Existing `Job.posted_at`; ORM synonym `published_at`, no duplicated stored date |
| Date semantics | `Job.publication_kind`, source-record `publication_kind` |
| First / latest successful observation | Existing `first_seen_at`, `last_seen_at` on Job and JobSourceRecord |
| Source modification | `last_modified_at` on Job and JobSourceRecord; not publication |
| Retrieval | `fetched_at` on Job and JobSourceRecord |
| Source provenance | Existing raw JSON, source ID, external ID, original URL; source-record publication fields |
| Authoritative presence | Nullable `JobSourceRecord.is_listed`; legacy presence is initially unknown |
| Material history | `job_revision` before/after snapshots, source record, type, observed time; Job.material_updated_at |
| Saved workflow | `Job.saved_stage`, `next_action`; application outcome remains on Application |
| Sponsorship display | Cached status, evidence JSON, checked time and valid-until; evidence expiry also respected by SQL filters |
| Match evidence | Existing JobLaneMatch score, structured checks, reasons and algorithm version |
| Manual action provenance | ApplicationEvent source `user_manual`; ActivityEvent stores the score at recording time for later metrics |

Migrations `0016` and `0017` preserve existing rows. Legacy publication kinds
remain unknown where original semantics cannot be established. Failed/partial
feeds do not close jobs. Confirmed absence requires complete authoritative
snapshots; public windowed boards cannot prove closure or keep an officially
removed listing open. Repeated stable provider IDs update the same card. New
provider IDs may flag likely reposts/duplicates without deleting either history.
Material updates, reopenings, closures and source-URL changes are retained.

## Scheduling and cost

Settings → Discovery controls a 15–1440-minute global interval (default 30).
Existing pause preferences take precedence over `DISCOVERY_MONITOR_ENABLED`, which
is the first-run default. Provider/source floors always win, including manual
refresh: Remotive 360 minutes; Jobicy, SmartRecruiters and WWR 60 minutes; other
sources may configure longer minima. The monitor batches up to five due sources
into the existing bounded freshness workflow. Active discovery is reused;
SQLite leases, retry/backoff and idempotency remain in force.

Keep the optional legacy discovery/full-review environment schedules disabled
for the normal workflow. Docker now also defaults the legacy schedule off.
No paid model or data service was enabled. Discovery/matching/inbox work with
models disabled. The Mac, app and worker must remain awake; provider delay and
source cadence prevent a promise of instant or universal job discovery.

## Verification

- Before editing: **710 tests passed in 43.45s**.
- Final full suite: **763 passed in 60.35s**; all mocked/local, no paid services.
- Focused browser-workflow regression: **26 passed in 3.78s**.
- Ruff check and format checks pass (232 Python files); strict mypy passes
  (145 source files).
- Labeled fixture: 22 hand-labeled cases, zero false positives, false negatives,
  label mismatches or hard-gate violations. This is a regression fixture, not
  measured production precision/recall. Existing saved user preferences remain
  unchanged.
- Browser: inspected live New Jobs, collapsed/expanded filters and last-24-hour
  discovery filtering; mobile width 390px has no horizontal overflow. Confirmed
  a real Chime original listing opens to the matching title/location; no Apply,
  form, login or submission action was taken. Checked Save → manual date/notes →
  application record → Applications in a separate synthetic test database.
- Live database upgraded to `0017` after a verified backup. Compared against the
  pre-change backup: all rows in 17 private/profile/application tables identical;
  190 private document/template/reference files unchanged; SQLite integrity OK.
  Includes 11 projects, 3 experiences, 6 application records and 41 documents.
- Live refresh: 25 enabled sources have successful observations, no current source
  errors or overdue checks at verification. WWR remains partial because one feed
  item fails validation; existing jobs remain visible and the issue is disclosed.
  Source health is time-sensitive, not a lasting availability guarantee.

Run checks from the repository:

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests scripts migrations
.venv/bin/ruff format --check src tests scripts migrations
.venv/bin/mypy src
.venv/bin/python scripts/evaluate_matching.py
```

## Manual acceptance check

1. Start the Desktop launcher; open `/new-jobs`.
2. Inspect source versus first-discovered dates. Use More filters if needed.
3. Open a direct employer/source link. Inspect requirements there; apply yourself
   only if you decide to. CareerOS does not click Apply or submit forms.
4. Save a role, add a next action, then return to it in Saved Jobs.
5. After independently applying, choose I applied manually, confirm, and record
   the date. Verify the dated record and notes under Applications.
6. Optional tools expose resume/cover-letter work; they are not required steps.
7. Inspect source status in Advanced → Monitoring evidence and quality metrics in
   Advanced → Discovery quality. Failures remain visible without clearing data.

## Honest remaining limits

- No site-wide authenticated LinkedIn/Handshake scraping or guaranteed coverage
  of every company. Supported public adapters and explicit user intake remain
  the permitted sources.
- URL validation establishes usable destinations, not independent HTTP or job
  availability. The quality report labels external HTTP availability unknown;
  one successful manual spot check does not certify the whole inbox.
- Likely duplicates are candidates, not a verified duplicate-rate measurement.
  Publication latency only uses trustworthy original timestamps and nonnegative
  delays; republish/unknown dates are excluded.
- Unknown sponsorship, seniority and other eligibility remain visible concerns;
  neither matching nor user review invents work authorization or an employer policy.
- Interview rates require actual recorded outcomes. Old applications without
  score-at-recording evidence remain unknown for score-band reporting.
- Docker configuration was updated for the default monitor but a Docker image
  was not built in this verification. The native Mac launcher/server was tested.
