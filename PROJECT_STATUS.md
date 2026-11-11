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
- **Surface**: `/today` page; `careeros discover` writes `exports/digest-YYYY-MM-DD.md`.
- 812 tests pass; ruff and strict mypy clean.

## Verified against real data

On 2026-11-11 the community feed was fetched live: 1,344 current listings → 1,158 rejected
(1,105 outside target role families, 47 outside the US, 5 seniority, 1 not full-time), 143 in the sponsorship
research queue, 43 needing review. The Workday, Greenhouse, Lever and Ashby adapters are
verified against fixtures only in this session, because the build environment could not reach
those hosts. Their first live run happens on the candidate's Mac.

## Not done yet

- First live run of the 220 official boards (run `./Run Discovery.command`).
- LCA data import (manual download; until then nothing can reach Level B, so the Eligible
  list stays empty by design).
- Scheduled discovery for the new source types through the existing worker is untested.
- Confirmed-alias mechanism for employer legal entities (possible matches stay Level C).
- Live URL re-check before calling a job "open" (today: "listed at last successful run").
- Lane matcher and New Jobs inbox still run in parallel with Today.

## Candidate input needed

1. Confirm official program end date and the OPT timeline with the BU ISSO. The stored
   "authorized until 2027-05-17" has no recorded source.
2. Confirm relocation: the stored profile says open to anywhere in the US.
3. Confirm role priority: Data Analyst and Data Engineer primary, the other families secondary.
4. Download the LCA disclosure file (see `docs/SPONSORSHIP_EVIDENCE.md`).

## Next, in order

1. Live run on the Mac; fix whatever real Workday tenants reveal.
2. LCA import → first Level-B eligible list; add confirmed entity aliases.
3. Phase 2: connect the Today card to the existing resume tailoring and application record.
4. Daily digest on a schedule; weekly strategy review using real funnel numbers.
5. Retire the lane matcher, missions and local-model runtime; then the frontend decision.
