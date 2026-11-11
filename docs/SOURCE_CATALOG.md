# Source catalog

All sources are public, unauthenticated endpoints. Each adapter has its own rate limit,
bounded retries with backoff, and failure isolation; a source that returns 403/429 three
times is disabled automatically. Health is on `/sources` and summarized on `/today`.

| Type | Access | Role | Notes |
|---|---|---|---|
| `greenhouse` | Public Job Board API | Official employer postings with full text | Full snapshot; absence closes a job |
| `lever` | Public postings API | Official | Full snapshot |
| `ashby` | Public posting API | Official | Full snapshot |
| `smartrecruiters` | Public postings API | Official | Hourly minimum interval |
| `workday` (new) | The careers site's own CXS JSON (`/wday/cxs/{tenant}/{site}/jobs`) | Official; reaches banks, asset managers, insurers and consultancies that the other ATSs do not | robots.txt is checked first. Searches "analyst", "data", "associate", 3 pages each; posting text fetched once per new plausible title, 20 per run. Partial snapshot: absence never closes a job. 6-hour minimum interval |
| `community` (new) | SimplifyJobs New-Grad-Positions `listings.json` on GitHub | Breadth: a curated list of current new-graduate roles, each linking to the employer posting | Third party. No posting text. Its sponsorship tag is Level C at most. 2-hour minimum interval |
| `remotive`, `jobicy`, `wwr` | Public APIs / RSS | Supplementary remote boards | Aggregators; never canonical |

## How coverage grows without guessing

`careeros sources harvest` reads employer posting URLs from the community list (and from jobs
already stored), extracts the ATS board each URL belongs to, and writes
`config/sources.discovered.toml`. Board tokens are never invented. Employers that already post
roles in the target families are listed first. The file committed on 2026-11-11 holds 220
boards (120 Workday, 45 Greenhouse, 22 Ashby, 19 Lever, 14 SmartRecruiters).

Community stubs and official records for the same posting merge on canonical URL, and the
official text replaces the empty stub, which is what lets the eligibility engine verify
experience requirements and sponsorship wording.

## Honest limits

- This is not the whole US market. It is the set of employers reachable through these ATSs
  plus one curated list.
- Not covered yet: iCIMS, Oracle Cloud, SuccessFactors, Taleo, Handshake (needs BU login),
  Built In, Wellfound, LinkedIn, Indeed. LinkedIn is not scraped.
- Workday runs are keyword-bounded, so a role with an unusual title can be missed.
- "Currently open" means "listed at the last successful run", not a live check of the page.
