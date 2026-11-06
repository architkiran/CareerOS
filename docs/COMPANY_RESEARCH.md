# Company workspaces and evidence freshness

`/companies` collects the candidate's explicit company watchlist, tracked active
postings, application counts, configured feed coverage and a research workspace
per company. Counts describe this local database, not the employer's whole hiring
market. Preparing a watchlist creates local records; it never asserts sponsorship.

Research leads captured by the assistant remain pending, even if an input attempts
to mark them checked. Only an explicit user review can accept them. A third-party
source remains a lead after acceptance and cannot establish authorization policy.
Business context uses the `other` claim type and does not affect eligibility.

The employer-research agent prepares these workspaces alongside its job-specific
research. It does not browse authenticated sites, automate LinkedIn, contact anyone
or infer immigration facts from employer reputation.

Policy freshness uses the older of source date and retrieval date. Re-reading an
old statement cannot make it current. Accepted official evidence older than 180
days leaves current sponsorship policy unknown and low-confidence; stale clearance
statements also cannot establish a current restriction. Job-specific current
evidence still takes precedence, and conflicting current evidence stays unknown.
The matching algorithm is versioned `match-v3` to invalidate older cached results.

Company forms use CSRF protection and private cache headers. Source links must be
HTTP(S) URLs with a host and no embedded credentials. No source content is fetched
by the evidence form itself. Tests cover pending leads, review isolation, stale
source dates, third-party limitations, missing companies and unsafe links.
