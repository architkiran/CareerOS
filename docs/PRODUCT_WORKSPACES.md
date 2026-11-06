# Simpler product workspaces

The primary navigation now has five destinations: Home, Opportunities, Applications,
Insights and Career library. Related pages are tabs within each area. Existing
URLs, history and useful services remain intact. System status and settings are
secondary tools instead of additional top-level career pages.

The interface defaults to a neutral light palette, with an optional neutral dark
mode. The Home view shows active tasks across every mission type, an accessible
match-distribution chart and next actions. Detailed review results, mission history
and system diagnostics use progressive disclosure. Mobile navigation keeps all five
primary destinations visible rather than hiding them in a long horizontal list.

The project runs from Desktop/PersonalProjects/CareerOS/CareerOS on
feature/careeros-2-product-workspaces. A verified snapshot of the previous candidate
workspace was restored into data/candidate-v2 and private paths rebased. The original
local database and environment configuration were preserved for recovery. Runtime
inference and both schedulers remain disabled.

The master LaTeX PDF renderer retains the supplied preamble. Variable text is escaped
and comes from verified profile content. Downloads use Archit_Kiran_Kumar_Resume.pdf;
job, company and version are labels inside Resume studio. A bounded selection of
projects/experience can be changed without editing facts or changing layout settings.
One-page, US Letter, overflow and binary/source integrity checks gate approval. Old
Word drafts remain accessible as legacy versions. Profile notes are excluded from
resume text; missing dates and unverified claims remain visible review warnings.

The compiler is local Tectonic. Normal generation uses untrusted mode, cached-only
resources and a 90-second timeout, without a shell. pypdf reads generated page metadata.
No model or paid service is required. Compiler binaries/cache and private source
resumes are excluded from Git. The private master source is included in backups.

SmartRecruiters adds a fourth public API adapter, explicitly scoped to US postings.
It fetches complete listing/detail snapshots with existing request limits. Boards
larger than 200 postings, incomplete pagination or changing detail records fail
without closing existing jobs. Source intelligence runs through durable missions,
audits configured coverage and proposes reviewed catalog feeds. It never claims an
exhaustive web search, guesses credentials, bypasses access restrictions or silently
re-enables disabled feeds. Connecting a proposal is an explicit reversible action.

Live checks: Wise returned 33 US postings, all normalized successfully. Databricks
and Fivetran public feeds were verified as additional suggestions. An unavailable
dbt Labs board was not added. Publication timestamps retain source provenance.
