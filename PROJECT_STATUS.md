# Project status

Last updated: 2026-11-11. Branch: `feat/career-os-2-discovery-eligibility`.

## Working now (tested)

- **Phase 0**: audit (`docs/AUDIT_2026-11-11.md`) and architecture decision
  (`docs/adr/0009-career-os-2-incremental-replacement.md`).
- **Discovery**: Workday adapter, community new-graduate feed adapter, board harvester,
  220-board watchlist in `config/sources.discovered.toml`.
- **Eligibility**: one verdict per job from six deterministic checks
  (`docs/ELIGIBILITY_RULES.md`).
- **Sponsorship evidence**: levels A/B/C/D/U with quotes and sources; DOL LCA importer
  (`docs/SPONSORSHIP_EVIDENCE.md`).
- **Confirmed employers**: on a Today card with a similar-name LCA filer, you can confirm the
  legal entity; that employer's roles are re-evaluated immediately (Level C → B).
- **Application actions on Today**: Prepare application (eligible roles) and I applied, using
  the existing tailoring workspace and application record.
- **Always current**: the worker re-evaluates verdicts and rewrites the digest after every
  scheduled discovery.
- **Interface v2**: new shell (slim rail, command palette on Cmd+K, page transitions, light
  and dark) and a rebuilt Today: queue tabs, list and detail side by side, keyboard triage
  (J/K, O, S, X, 1/2/3, /), instant save and dismiss. Colour is reserved for sponsorship
  evidence. Navigation cut from 22 links to 13; agent, mission and market pages are unlinked.
- **Reach a person**: every role has people-search links and editable drafts (connection
  note within 300 characters, recruiter question, follow-up). Nothing is ever sent.
- **Workday fixed after the first live run**: robots.txt was requested as JSON and Workday
  answered 406 for 111 of 120 sites. Verified against a live Workday site on 2026-11-11.
- **Surface**: `/today` page; `careeros discover` writes `exports/digest-YYYY-MM-DD.md`.
- 801 tests pass; ruff and strict mypy clean.

## Verified against real data

On 2026-11-11 the community feed was fetched live: 1,344 current listings → 1,158 rejected
(1,105 outside target role families, 47 outside the US, 5 seniority, 1 not full-time), 143 in the sponsorship
research queue, 43 needing review. The Workday, Greenhouse, Lever and Ashby adapters are
verified against fixtures only in this session, because the build environment could not reach
those hosts. Their first live run happens on the candidate's Mac.

## Removed on 2026-11-11

- Market intelligence (briefs, page, agent step): 12 briefs produced, none used.
- Remotive and We Work Remotely are switched off (migration 0019): 176 postings, none
  eligible or worth researching. Their adapters remain if you want them back.
- Ten superseded planning and validation documents, research notes and an unused stylesheet.

Still present but superseded, to remove after Today has been used for a week: the lane
matcher, the old New Jobs inbox, Mission Control and the agent activity pages.

## Not done yet

- First live run of the 220 official boards (run `./Run Discovery.command`).
- LCA data import (manual download; until then nothing can reach Level B, so the Eligible
  list stays empty by design).
- Live URL re-check before calling a job "open" (today: "listed at last successful run").
- Scheduled runs of the Workday and community sources through the worker have not been
  observed live yet.
- Lane matcher and New Jobs inbox still run in parallel with Today.

## Candidate input needed

1. Confirm the work-authorization dates stored in the profile with the university
   international office. One stored date has no recorded source.
2. Confirm relocation: the stored profile says open to anywhere in the US.
3. Confirm role priority: Data Analyst and Data Engineer primary, the other families secondary.
4. Download the LCA disclosure file (see `docs/SPONSORSHIP_EVIDENCE.md`).

## Next, in order

1. Live run on the Mac; fix whatever real Workday tenants reveal.
2. LCA import → first Level-B eligible list; confirm legal entities for target employers.
3. Phase 2: outreach drafts and referral paths from the Today card; follow-up reminders.
4. Daily digest on a schedule; weekly strategy review using real funnel numbers.
5. Retire the lane matcher, missions and local-model runtime; then the frontend decision.
