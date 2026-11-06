# Evidence-backed career intelligence

The version-2 career review adds a market step after matching. Existing version-1
missions continue using their persisted five-step graph; they are not rewritten.

`/market-intelligence` builds immutable, deduplicated briefings from saved public
postings. It is an exploratory analysis of the configured company set, not a claim
to monitor the whole employment market or discover lower-competition openings.

## Evidence and candidate grounding

Eight code-defined themes cover analytics engineering, financial data operations,
fraud/risk analytics, product decisions, data quality, business systems, operations
analytics and applied data science. These are research hypotheses. A theme appears
only when actual saved postings match its title terms and mention at least two
verified candidate skills. No unverified skill is used as supporting evidence.

Each finding includes counts of jobs/employers, verified skill overlap, additional
skills to review and up to five source-linked postings. It preserves job IDs,
source name/URL, first seen, last seen, source timestamps, saved fit scores and
eligibility state. Unknown eligibility stays unknown. Existing failed matches,
closed/rejected jobs, stale or future-dated observations, disabled sources,
unsafe evidence URLs and clearly senior titles are excluded.

The seven-day default window concerns **last observation**, not publication.
Greenhouse `updated_at` is not publication evidence. Ashby `publishedAt` and
Greenhouse `first_published`, when present, are labelled as source publication
fields; Lever `createdAt` is labelled source creation. A first-seen time is never
presented as publication time.

## Persistence and trends

Migration 0012 adds `market_brief`: input hash, verified-profile input hash,
creation time and strict structured report JSON. There are no prompts or raw
candidate documents in the report. Source text has no execution/tool privileges.
Repeated unchanged inputs on the same day reuse the same briefing.

Comparison requires an earlier day, the same verified profile, lookback window,
algorithm and enabled/fresh source coverage. Same-day repeated runs and coverage
changes cannot establish a trend. Even a comparable delta is explicitly a change
in the tracked corpus, not a market-wide hiring rate, causal effect or proof of an
emerging career category.

The **Build from saved postings** form performs local analysis only and is CSRF
protected. A full career review first refreshes sources. New briefs also appear
in Mission Control and the intelligence agent has a persisted mission history.

## Source access scope reviewed

The existing adapters use published job-board interfaces:

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board): public GET
  endpoints; no application POST is used.
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api):
  published job postings and the documented compensation option; unlisted entries
  remain excluded.
- [Lever Postings API](https://github.com/lever/postings-api): public published
  postings; no application endpoint or logged-in content is accessed.

Reviewed November 6, 2026. Documentation is evidence of the interface's intended
public data flow; it is not blanket permission for every third-party website.
Retain bounded requests, rate limits and refusal handling. No new paid provider,
proxy, browser scraper or authentication bypass was introduced.

## Validation at this milestone

Full suite: **525 passed in 26.37 seconds**. Ruff and strict mypy passed. Focused
checks cover grounded findings, no simulated empty-state intelligence, URL safety,
source timestamps, stale/closed/future/rejected/disabled exclusion, idempotence,
rollback, comparable daily baselines, changed coverage/profile, CSRF, escaped
source text, and version-1 mission compatibility.

A live review in the isolated copied workspace refreshed 17 configured feeds,
found 16 new jobs, updated 18, and completed all six steps successfully. Its first
briefing contained four evidence-backed themes across 3,560 recently observed
active/non-rejected jobs. These user-specific results are in the private local
database, not source control. The original workspace was not modified.

## Limits

Title themes are curated rules, not unconstrained language-model discovery.
Industry publications, employer announcements, community signals and wider company
coverage are later research sources. There is no claim of low competition,
verified sponsorship or eligibility based on a role-theme match. Exact resume
layout preservation is a separate, unfinished capability.
