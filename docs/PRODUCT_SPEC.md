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

## Primary user journey (implemented 10 November 2026)

Discover → inspect the original employer/provider page → save or dismiss → apply
independently on that page → explicitly record the completed application.

## Main screens

- **New Jobs** (`/new-jobs`, default landing): since-last-visit inbox, direct
  original links, source dates, discovery dates, up to three evidence-based
  reasons and the most important concern. Uncertain eligibility remains visible;
  explicit hard failures cannot be promoted by a keyword score.
- **Saved Jobs** (`/saved-jobs`): shortlist status and next action; original link;
  user-confirmed manual application recording. Resume/cover-letter tools are
  optional disclosures, not prerequisites.
- **Applications** (`/applications`): dated user records, outcomes, original links
  and notes. Unsubmitted preparation work is preserved under Advanced.

Advanced / Settings retains evidence, analytics, documents, approvals, referral
research, monitoring, agents, backup and configuration. Neither applications nor
messages are sent. Default monitoring is 30 minutes with stricter source limits,
visible failures and no claims of instant site-wide coverage.

See [the implementation report](SIMPLIFICATION_IMPLEMENTATION.md) for acceptance
checks, migration mappings and measured limits. The remaining contracts describe
retained optional capabilities rather than required steps for each job.

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
