# Permitted monitoring and contact research

## How can CareerOS prove freshness and monitor reliably?

### Takeaway
Publication, update, first observation and last check are different facts. Monitoring can reduce detection delay but cannot promise minute-level awareness on delayed or daily feeds.

### Cited Findings
- Greenhouse permits unauthenticated GETs. List examples contain `updated_at`; retrieve-one examples also contain `first_published`. These must not be conflated. Public metadata is employer-selected rather than a universal manager directory. — [Greenhouse Job Board API](https://docs.greenhouse.io/job-board)
- Ashby documents `publishedAt` as the time a posting was **last** published. `isListed=false` means direct-link only and should not appear in public lists. Missing fields may simply be absent from responses. — [Ashby public Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)
- Lever's reviewed public schema does not document `createdAt`. Its published 2/second limit concerns application POSTs, not a guaranteed public GET allowance. — [Lever postings API](https://github.com/lever/postings-api)
- SmartRecruiters posting examples contain `releasedDate` and sometimes a creator name. A creator is not automatically the role's hiring manager. — [SmartRecruiters endpoints](https://developers.smartrecruiters.com/docs/endpoints)
- Remotive intentionally delays public listings by 24 hours and advises at most four fetches/day. — [Remotive API](https://github.com/remotive-com/remote-jobs-api)
- Jobicy's feed is a seven-day publication window; missing records need not be closed. Automated synchronization must be no more than hourly. Its free status endpoint accepts up to 100 stored IDs; results reflect Jobicy records, not a live employer check. Retain attribution and original URLs. — [Jobicy API](https://github.com/Jobicy/remote-jobs-api)

### Inferences
- Separate filters: **Source-published in 24h**, requiring a real publication timestamp, and **Found in 24h**, based on local observation. Unknown dates remain unknown. Say **Last published** for Ashby and **Source updated** for Greenhouse `updated_at`.
- Persist provenance: source field/basis, publication time, update time, first/last observed time, last check, original URL, content hash, provider lag. Do not backfill a missing publish time from first observation.
- Show monitoring state, cadence, last success, next due, stale heartbeat, scope and errors. Say monitoring runs while CareerOS and its worker run; a stopped process or sleeping laptop is not continuous monitoring.
- Treat a configurable conservative interval for employer feeds as CareerOS policy, not a vendor SLA. Stagger fetches, respect Retry-After and blocking, and avoid claiming instant detection.
- New-job alerts should deduplicate by stable IDs. An initial import is a baseline/digest, not thousands of jobs falsely called freshly posted.

### Gaps
- No universal public push webhook or vendor guarantee of minute-level publication was established.
- Greenhouse list responses do not uniformly promise first publication. Bounded detail enrichment may help, but some postings still have no proof.
- No specific unauthenticated GET polling entitlement was found for Greenhouse, Lever or SmartRecruiters. Do not transfer authenticated account API limits to unrelated endpoints.

## Which additional free sources fit the product?

### Takeaway
Add documented APIs and officially permitted RSS, with source-specific cadence and honest scope. WWR is straightforward RSS; Himalayas adds filtered remote breadth but refreshes daily.

### Cited Findings
- WWR expressly permits anyone to reuse its public RSS with backlink attribution, including all-jobs, management/finance and product feeds. — [WWR public RSS](https://weworkremotely.com/remote-job-rss-feed)
- Himalayas has unauthenticated browse/search, US and seniority filters, at most 20 jobs/page, cursor pagination, and daily refreshed data. Preserve `applicationLink`, visible attribution, and remove expired jobs. Single-job checks return 200 open, 410 closed, 404 absent, and may be cached ten minutes. Optional free keys raise limits; unauthenticated callers share a public allowance. — [Himalayas API](https://himalayas.app/api)
- USAJOBS Search needs an API key and identifying email; codelists do not. Queries cap at 10,000 results and 500/page. — [Authentication](https://developer.usajobs.gov/guides/authentication), [limits](https://developer.usajobs.gov/guides/rate-limiting)
- LinkedIn restricts scraping/copying profiles/data and unauthorized bots for contacts/messages. Handshake prohibits bulk automated collection of jobs and marketplace data. — [LinkedIn agreement](https://www.linkedin.com/legal/user-agreement), [Handshake terms](https://joinhandshake.com/legal/tos/)

### Inferences
- WWR implementation: fixed allowlisted host, secure XML parsing, size limits, attribution and provider-safe cadence. Finite RSS absence must not close saved jobs automatically.
- Himalayas implementation: daily US/entry-level filtered queries, bounded pagination and GUID deduplication. Distinguish a bounded query from a complete feed snapshot. Recheck a single job before application preparation; do not promise minute updates.
- USAJOBS should stay optional and unconfigured without an existing key. Do not create accounts or ask for credentials unnecessarily; work eligibility remains posting-specific.
- Expand employer watchlists by sector only after checking feed identity and access. Unsupported career platforms can use assisted import until a reliable permitted connector exists.
- LinkedIn/Handshake native saved searches/alerts and manual imports can complement CareerOS without collecting passwords or cookies.

### Gaps
- WWR RSS permission does not guarantee free applications for every listing or a fixed publication SLA.
- These public boards favor remote work. Manufacturing/consulting breadth still needs direct employer feeds.

## What useful contact and verification agents can run truthfully?

### Takeaway
Agents should save evidence-backed artifacts and clearly distinguish search plans, unverified leads, verified people and verified recipient addresses. No free public ATS directory reliably identifies the hiring manager for every opening.

### Cited Findings
- CapTech's official careers page warns of recruiter impersonation, lists recruiting email domains, and provides purpose-specific verification/scam reporting. That inbox is not automatically a cold-email target. — [CapTech careers](https://www.captechconsulting.com/careers)
- Formlabs' careers site warns agencies not to forward resumes to its alias/employees; audience and purpose matter when interpreting public contact text. — [Formlabs careers](https://careers.formlabs.com/)
- Employer-selected ATS metadata may contain extra fields, but does not establish a universal people lookup. — [Greenhouse API](https://docs.greenhouse.io/job-board)
- LinkedIn's native professional networking does not remove its restrictions on scraping and unauthorized automated access. — [LinkedIn agreement](https://www.linkedin.com/legal/user-agreement)

### Inferences
- **Freshness verifier:** audit timestamp basis, invalid/future dates, stale checks and provider lag; save a report.
- **Availability checker:** revalidate via permitted canonical API/status endpoint before preparing an application. Keep open/closed/unknown/unreachable separate; a timeout is not closure.
- **Application evidence mapper:** extract JD requirements, link verified candidate facts, expose gaps, hand off to resume and interview preparation.
- **Networking researcher:** on application start, produce target functions (recruiter covering the role, relevant team lead, BU alumnus), official career/team source links and user-assisted search queries. A search result is an unverified lead until checked; a named public employee may be irrelevant to this opening.
- **Outreach drafter:** create a company/role-specific email and connection note using a verified project plus JD context. Leave names/recipients blank without evidence. Never synthesize email patterns, past relationships or familiarity with someone's work. Store draft evidence separately from send approval.
- **Follow-up planner:** suggest timing from actual application dates, detect duplicate pending outreach, save drafts; do not schedule sends or external calendar events implicitly.
- Contact evidence needs role, employer, source URL, excerpt, checked time, source purpose and verification status. Knowing a person's identity and verifying a suitable address are different steps.

### Gaps
- Often a useful honest output is a research plan and draft before any verified contact exists. Universal names/emails, comprehensive people coverage and current employment cannot be guaranteed.
