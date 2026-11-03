# Pipeline design

## Pipeline overview

```text
SCHEDULE
  ↓
DISCOVER SOURCES
  ↓
FETCH WITH LIMITS
  ↓
PARSE + NORMALIZE
  ↓
VALIDATE + DEDUPLICATE
  ↓
HARD FILTERS
  ↓
ROLE-LANE CLASSIFICATION
  ↓
EXPLAINABLE SCORING
  ↓
OPTIONAL EMPLOYER / AUTHORIZATION RESEARCH
  ↓
SHORTLIST / USER TRIAGE
  ↓
GENERATE DOCUMENT DRAFTS
  ↓
FACT CHECK + QA
  ↓
HUMAN APPROVAL
  ↓
USER SUBMITS / SENDS
  ↓
TRACK OUTCOME + LEARN
```

## Discovery adapters

Start with public job-board endpoints:
- Greenhouse public job board feeds;
- Lever public postings;
- Ashby public job board postings;
- explicitly configured company career pages with permitted access.

Each adapter implements:
- `list_jobs(source_config)`;
- `fetch_job(external_id)`;
- `normalize(raw) -> NormalizedJob`;
- source attribution and retrieval timestamp;
- rate-limit and retry policy.

Keep adapters isolated. A broken source must not break the entire run. Add source-specific fixtures and contract tests. Company pages are opt-in and must be checked for terms/access restrictions. Avoid broad scraping. Do not use LinkedIn scraping or unauthorized browser automation.

## Normalize

Normalize:
- title, company, location, workplace type;
- employment type and seniority;
- description and requirements;
- salary range and currency when explicit;
- posted/updated date;
- source URL and external ID.

Do not infer undisclosed salary, sponsorship, remote eligibility, or seniority as fact. Store inferred classifications with confidence and rationale.

## Dedupe

Deduplication precedence:
1. same source + external ID;
2. canonicalized URL;
3. same company + normalized title + location + close description similarity/hash;
4. possible duplicate requiring review.

Do not discard source provenance. Canonical job may have several source records.

## Hard filters

Each filter returns `{decision: pass|fail|unknown, reason, evidence}`.
- full-time requirement;
- internship/contract exclusion;
- location/relocation;
- role lane exclusions;
- seniority;
- work authorization restrictions;
- stale/closed status.

Unknown is surfaced. Avoid false certainty.

## Scoring

Return:
- total 0-100;
- per-dimension score and weight;
- matched evidence;
- missing skills;
- risks;
- confidence/completeness.

Never make a single opaque LLM score the source of truth. The base score is deterministic. An optional model may summarize or classify ambiguous descriptions, but must return structured data validated by Pydantic and cannot override hard filters.

## Employer research

Research tasks are queued only for shortlisted or borderline jobs to conserve time and compute. Prioritize:
1. official job description;
2. official company careers/immigration page;
3. public government/company filing data if relevant and legally accessible;
4. reputable third-party reports as secondary evidence.

Record claim, source, retrieval date, evidence excerpt, and confidence. Sponsorship is role- and employer-specific. "Company sponsored someone before" does not prove this job will sponsor.

## Document workflow

1. Select role-lane resume base.
2. Retrieve only relevant verified profile facts.
3. Map each proposed claim to source facts.
4. Generate a draft using deterministic templates first.
5. Optional local model may improve wording, never invent content.
6. Run checks: unsupported numbers, missing evidence, contradictory dates, skill not in profile, altered employer/title, inflated ownership.
7. Render DOCX; PDF export is optional if LibreOffice exists.
8. Save immutable version and diff.
9. Add to approval queue only after QA passes or warnings are explicitly acknowledged.

## Application answer handling

Keep reusable answer bank for factual questions, but never auto-fill legally significant declarations without review. Questions about sponsorship, visa, work authorization, disability, demographic information, criminal history, and legal attestations require direct user input/review. Do not infer an answer from profile text.

## Follow-up and outcome learning

Track:
- submitted date;
- source and resume version;
- recruiter contact and outreach;
- response dates;
- screen/interview rounds;
- rejection/withdrawal/offer;
- reason if known.

Learn at aggregate level: interview rate by role lane, source, company size, resume version, and application cohort. Do not overfit from tiny samples. Recommend adjustments with sample sizes and confidence intervals.
