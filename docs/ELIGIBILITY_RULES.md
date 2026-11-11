# Eligibility rules (engine `elig-v1`)

Code: `src/careeros/modules/eligibility/engine.py`. Tests: `tests/unit/test_eligibility_engine.py`
(every case in mission spec 19.1) and `tests/integration/test_career_os_2.py`.

The engine is deterministic. No language model takes part in a hard decision.

## Verdicts

| Verdict | Meaning | Where it shows |
|---|---|---|
| `eligible` | Every hard rule passes and sponsorship evidence is Level A or B | Today → Eligible |
| `research` | Every other rule passes; sponsorship is Level C or U | Today → Sponsorship research queue |
| `review` | Some other hard criterion could not be read from the source | Today → Needs your review |
| `rejected` | At least one hard rule failed | Hidden; reason stored in `job_verdict` |

Each check returns `pass`, `assumed`, `unknown` or `fail`. `assumed` means the source does not
state the fact and nothing contradicts the default. It counts as a pass but is displayed as an
assumption, so nothing is passed silently.

## The six checks

| Check | Fail | Unknown (review) | Pass |
|---|---|---|---|
| Target role family | Title matches no family in spec 4.1 | Generic "analyst" title outside the named families | Title matches a family |
| Currently open | Source no longer lists it | Not seen in a successful run for 4+ days | Listed at the last run |
| US work location | Names only non-US places | No location; remote without a country; remote restricted to listed states | US place, or remote with US wording |
| Full-time | Title says intern, co-op, contract, temporary, part-time, seasonal, fellowship, apprentice; source states a non-full-time type | Posting text mentions mixed types | Source or posting says full-time. **Assumed** when unstated with no contrary wording |
| Early career | Senior/staff/lead/principal/director title; manager without an entry pathway; explicit requirement of 3+ years | 2 years mentioned; years conflict with new-grad wording; no stated requirement and no entry pathway; no posting text | 0 to 1 years stated, or explicit new-graduate / entry-level pathway. **Assumed** for a text-less listing on a curated new-graduate list |
| Sponsorship pathway | Level D | Level C or U; candidate need unconfirmed | Level A or B |

Deliberate choices:

- "Analyst", "associate" or "junior" in a title is never proof of entry level (spec 3.3).
- Fixed-term wording ("12-month contract") is flagged on the card, not treated as permanent.
- The candidate's own sponsorship need comes only from a verified work-authorization record.
  If unconfirmed, nothing can be `eligible`.
- Level B passes the gate but the card says "role sponsorship unconfirmed" and supplies the
  recruiter question. It never claims the role sponsors.

## Fit (shown only for non-rejected roles)

Strong / Good / Stretch from transparent points: primary family +2 (secondary +1), verified
skills named in the posting (4+ → +2, 2+ → +1), sponsorship A +2 / B +1, published within
7 days +1, Boston area or remote +1. Strong ≥ 5, Good ≥ 3. This is a sorting heuristic. It is
not a probability of being hired and is labelled as such in the UI.

## Changing a rule

Edit the engine, add or change a test that states the expected verdict, bump `ENGINE_VERSION`,
run `careeros discover --no-fetch` to re-evaluate stored jobs.
