# Quality, observability, and success metrics

## Current default workflow — 10 November 2026

Advanced → Discovery quality (`/quality`) reports relevant discoveries by day,
original-publication observation delay, usable URL coverage, possible duplicate
candidates, local open/save/dismiss/review/application events, explicit user
eligibility reviews, and outcome rates by recorded score band. Existing analytics
provides role/source outcomes. URL syntax coverage is not HTTP availability;
possible duplicates are not a verified duplicate rate. Missing historical score
snapshots stay unknown. The 22-case labeled matching fixture separately tests
relevance and hard gates; it is not a production accuracy estimate.

[Verified implementation and limits](SIMPLIFICATION_IMPLEMENTATION.md).


## Operational health

Track:
- last successful run per source;
- jobs fetched/new/updated/duplicate/filtered;
- task queue depth and oldest queued age;
- retries and dead-letter count;
- pipeline duration;
- source error rate and HTTP status distribution;
- dashboard SSE connection status;
- DB backup age;
- model spend and cache hit rate.

Show actionable errors. Do not hide failures behind a green "completed" badge.

## Product funnel

Track counts and conversion rates:
- discovered;
- passed hard filters;
- shortlisted;
- researched;
- document prepared;
- approved;
- submitted;
- recruiter response;
- screen;
- interview;
- offer.

Segment by role lane, source, company, resume version, and time cohort. Always show sample size. Avoid claiming that a change caused improved outcomes from a tiny sample.

## Quality gates

- 100% of external actions pass through approval service.
- 0 fabricated profile facts in generated documents.
- 100% of job records have source provenance.
- deterministic matching reproducible by algorithm version.
- dedupe tests cover same source ID, canonical URL, and likely duplicates.
- adapter tests cover timeout, malformed payload, 403, 429, and server error.
- backup restore test documented.
- app usable with AI disabled and internet unavailable (except fresh discovery).

## User value

Optimize for qualified interviews, not raw application count. Early operating target: a small number of high-quality, well-researched applications per day rather than hundreds of generic submissions. Measure outcomes before changing weights or workflow.

## Mission Control query cost

With the copied personal workspace (~3,800 jobs and eight lanes), the original
Mission Control implementation loaded all lane-score JSON twice on every poll.
The dashboard now ranks minimal matching columns in SQLite, loads filter evidence
only for each winning lane, and fetches full job/match records only for the bounded
recent-opportunity feed. Best-lane ties use lane name and match ID consistently.

A local TestClient check measured approximately 3.5 seconds before and 0.34 seconds
after, with the live fragment at 0.26 seconds. These are development observations,
not a controlled benchmark or performance guarantee. Integration tests compare
counts/feed choices against the existing inbox behavior, including overrides and
disabled lanes. No cache, Redis, denormalized user data or new service was added.
