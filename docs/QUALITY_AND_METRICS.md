# Quality, observability, and success metrics

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
