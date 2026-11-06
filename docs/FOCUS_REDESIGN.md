# Focus workspace redesign

## What changed

The primary navigation is now Today, Opportunities and Applications. Today shows
three classified, score-ranked opportunities, varied by employer, plus concrete
next steps. Broad unclassified jobs remain in All postings. Scores prioritize
review; they do not establish candidate eligibility. Clinical coding consultants
no longer match a generic business-consulting keyword. Luxembourg postings are
recognized as outside the US. Matching version is `match-v4`.

Opportunities uses a searchable list and selected-job panel with evidence and
application actions. Applications uses a four-stage visual pipeline. Agent activity
shows working tasks, dependent work and persisted results, including background
matching and ingestion tasks outside missions. Detailed history remains one click
away. Secondary tools are disclosed progressively; no application or profile data
was removed. Layouts were checked in the live browser at desktop and mobile sizes.

## Resume pipeline

Every visible resume action and the application agent generates a PDF; compiler
failure retries or displays an error instead of substituting Word. Historical Word
versions and Word cover letters remain accessible. Downloads keep the exact basename
`Archit_Kiran_Kumar_Resume.pdf`; the application workspace supplies company, role,
version, selected evidence and the reasons for selection.

Tailoring is deterministic and local: the posting ranks verified projects, skill
ordering and experience bullets. In-progress projects receive a selection penalty;
their status is retained. No model invents a rewritten achievement. Education,
experience and metric claims retain their profile references. Editing instructions
are omitted. The immutable user-supplied LaTeX preamble controls formatting, and
page-count, overflow and integrity checks remain. Same-origin inline PDF previews
are private and uncached. Three current draft applications were regenerated and
rendered as one-page US Letter PDFs. Missing dates and excluded unverified items
remain explicit warnings requiring the user's review.

## Discovery and access rules

Four public employer-feed adapters remain: Greenhouse, Lever, Ashby and
SmartRecruiters. Two documented public job-board APIs add broader coverage:

- [Remotive API](https://github.com/remotive-com/remote-jobs-api): retain the original
  listing URL and attribution; postings have a 24-hour publication delay. CareerOS
  enforces at least six hours between checks, including manual requests.
- [Jobicy API](https://github.com/Jobicy/remote-jobs-api): retain original URLs and
  attribution, use opaque cursor pagination with a bounded page limit, and enforce
  at least one hour between checks. This is a rolling listing window.

Absence from either windowed board never marks a previously saved job closed.
Real employer names are separate from source names. Original board URLs are
validated against the provider host. Board evidence is treated as third-party
research, not an authoritative employer policy statement.

Verified new employer connections are Formlabs (manufacturing) and CapTech
Consulting. Their first checks imported 238 and 97 postings, respectively. Remotive
and Jobicy first checks imported 12 and 761. These are source counts, not suitable
match counts; matching and review still apply. The local database held 4,947 jobs
across 22 enabled connections after those imports, before the subsequent live review.
Bosch was investigated but its 360 US postings exceeded the existing 200-posting
SmartRecruiters safety limit; it was not connected by weakening that limit.

[LinkedIn's User Agreement](https://www.linkedin.com/legal/user-agreement) restricts
unauthorized automated scraping. [Handshake's Terms](https://joinhandshake.com/legal/tos/)
also restrict scraping marketplace content. Their integration is user-assisted:
browse with your account, then paste an accessible posting and original URL into
Add a job. No credentials are collected and importing performs no remote fetch.
Imported jobs enter the same matching, research, preparation and approval workflow.
Unsupported employer sites can use this route too. CareerOS does not claim an
automated logged-in LinkedIn/Handshake crawler or universal career-site coverage.

## Open-source inspiration

These projects informed workflow decisions; no implementation code, branding or
assets were copied:

- [Job Application Tracker](https://github.com/waddington/job-application-tracker):
  a next-action home and visual application stages informed Today and Pipeline.
- [Job Ops](https://github.com/DaKheera47/job-ops): a local career workflow and
  review-oriented materials informed explicit PDF preparation and inspection.
- [Tailor Resume](https://github.com/narendranathe/tailor-resume): evidence-first
  tailoring informed the visible selection explanation and missing-fact boundary.
- [Reactive Resume](https://github.com/reactive-resume/reactive-resume): clear
  preview/export actions informed the PDF workspace.

We retained SQLite, the existing Python web architecture, verified profiles,
claim maps, approvals and durable missions. We did not add paid services, duplicate
agent frameworks, a new frontend toolchain, automatic outreach or submissions.

## Validation

The final suite passed 621 tests. Ruff and strict mypy passed. Coverage includes
job-dependent evidence selection, PDF download headers, compiler-failure retry
without Word fallback, CSRF and no-network manual import, public-board attribution,
refresh gaps, rolling-feed closure semantics, classification and location fixes,
three primary actions, and background-task visibility. Offline route tests use a
small PDF compiler stand-in; separate live validation uses real cached Tectonic
compilation and rendered PDF inspection. The live career review exercises actual
public feeds, durable task dependencies, matching and local reporting.

The product remains local-first. Ollama is optional; the active environment has
model inference disabled and the new functionality incurs no API charges. Scheduling
is configurable but remains disabled in the user's current environment; discovery
runs on request. Human review remains necessary for dates, work authorization,
sponsorship evidence, and every external application or outreach action.

The live six-step review completed and found 16 additional postings. It retained
an ingestion warning after one Coinbase refresh encountered SQLite write contention.
The feed was rechecked after the transaction fix: 283 postings fetched successfully,
5 additional jobs, 1 update, zero invalid postings and zero false closures. Historical
warnings remain preserved. Ingestion now reserves a SQLite writer explicitly for
short batches and marks unexpected interrupted runs failed in source health. A
regression test verifies completed batches persist and the interrupted batch rolls
back. The final snapshot contains 4,968 saved jobs.
