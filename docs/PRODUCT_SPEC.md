# Product specification

## Product goal

Help one candidate spend less time searching and more time getting interviews by turning fragmented job-search work into a measurable, explainable pipeline.

CareerOS is not an indiscriminate auto-apply tool. It is a career intelligence and application operations system.

## Candidate profile and target lanes

Support multiple role lanes instead of one blended resume:
- Data / BI Analyst
- Business Analyst / Business Operations Analyst
- Financial / Operations Analyst
- Product Analyst / Product Operations / Associate Product roles
- Management consulting / business transformation
- Selective Data Engineering roles

Each lane has its own:
- title and synonym rules;
- required/preferred skills;
- seniority constraints;
- resume base version;
- scoring weights;
- excluded titles and domains;
- location and compensation preferences.

The candidate's known strengths include SQL, Python, Power BI, analytics, dashboards, finance/business analysis, and graduate computer science study. The app must use only verified profile facts. The user must confirm exact dates, metrics, project details, graduation date, availability, compensation, and work-authorization answers before those facts are used externally.

## Primary user journeys

1. **Discover:** ingest jobs from approved sources and show source freshness.
2. **Triage:** remove duplicates and clearly irrelevant roles with deterministic rules.
3. **Understand:** show match score, score breakdown, missing skills, concerns, and evidence.
4. **Decide:** shortlist, reject with reason, or save for later.
5. **Research:** collect employer facts, role details, location, salary, sponsorship/authorization evidence, and source confidence.
6. **Prepare:** generate a truthful role-specific resume/cover letter/application answer draft.
7. **Review:** compare draft against candidate evidence and job requirements.
8. **Approve:** user reviews exact final payload and explicitly approves a single action.
9. **Act:** user submits manually or uses a permitted, supported workflow. Record the result.
10. **Learn:** track screens, interviews, rejections, offers, and response rates by role lane/source/resume version.

## Dashboard pages

### Overview
- today's new jobs;
- jobs passing hard filters;
- shortlist count;
- drafts awaiting review;
- approvals awaiting action;
- upcoming follow-ups;
- pipeline run status and last successful run;
- estimated model/API spend (must be $0 when no external model is configured);
- recent activity stream.

### Job inbox
- filter by lane, score, location, source, date, work authorization confidence, salary, status;
- search title/company/description;
- show duplicate group and canonical record;
- actions: shortlist, reject, save, mark reviewed.

### Job detail
- original source link;
- normalized description;
- role lane;
- hard-filter outcomes;
- score breakdown and explanations;
- required skills matched/missing;
- sponsorship/authorization evidence with source and confidence;
- company research;
- application history.

### Application workspace
- job-specific resume/cover letter/answers;
- source profile facts used;
- unsupported-claim warnings;
- version comparison;
- export DOCX/PDF;
- final approval checklist.

### Approvals
- exact action preview;
- destination and recipient;
- exact document/message version;
- risk warnings;
- approve, reject, or request edits;
- approval expiration and immutable audit record.

### Analytics
- funnel: discovered → qualified → shortlisted → prepared → submitted → response → screen → interview → offer;
- conversion by source, role lane, company, resume version, and week;
- median time in each stage;
- rejection/no-response reasons;
- application quality vs volume.

### Settings
- candidate profile and verified facts;
- role lanes and scoring weights;
- locations and relocation;
- work authorization status and dates, entered by user;
- source/company watchlist;
- run schedule, rate limits, retention, export/delete;
- optional local model configuration.

## Matching design

Use two stages.

### Stage 1: deterministic eligibility and relevance gates
- employment type must be full-time unless user explicitly enables another type;
- exclude internship/co-op/temporary/contract roles by default;
- location and relocation rules;
- seniority and experience constraints;
- role-family allow/deny terms;
- duplicate and stale posting checks;
- explicit work-authorization restrictions.

Unknown authorization status is **unknown**, not a pass and not a fail. Do not silently reject a job solely because the employer's policy is unknown. Flag for research/manual review.

### Stage 2: explainable score (0-100)
Initial suggested weights, configurable per lane:
- role/title alignment: 20
- skills alignment: 25
- experience/project evidence: 20
- seniority fit: 10
- location/work arrangement: 10
- compensation, when disclosed: 5
- employer/role preference: 10

Hard disqualifiers are separate from score. Missing salary must not become zero. Unknown sponsorship must not be treated as sponsorship available. Scores must show evidence and missing information, not just a number.

## Work authorization intelligence

This is a high-impact risk area. Store:
- candidate-entered status and relevant dates (never infer);
- employer policy status: sponsorship offered / no sponsorship / case-by-case / unknown;
- role-specific restrictions;
- source URL, source date, quoted short evidence, retrieval date;
- confidence: high / medium / low;
- reviewer and review date.

Prefer official employer immigration/careers pages and exact job descriptions. Third-party databases are leads, not proof. Do not provide legal advice. Present uncertainty and require user review for application declarations.

## Document generation

Generated documents must:
- be grounded only in verified candidate facts;
- preserve a fact-to-source map for claims;
- never invent numbers, technologies, ownership, outcomes, or years of experience;
- use role-lane base templates;
- include a diff from the base version;
- pass a contradiction/unsupported-claim check;
- be versioned and linked to the job.

## Non-goals for MVP

- automatic submission;
- automatic outreach sending;
- scraping LinkedIn or logged-in job boards;
- paid job-board APIs;
- autonomous agents that can browse and act without bounded tools;
- microservices/Kubernetes;
- vector database;
- mobile app;
- multi-user SaaS;
- expensive real-time model calls.
