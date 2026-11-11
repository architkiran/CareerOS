# Sponsorship evidence

Code: `src/careeros/modules/sponsorship/levels.py` (classification) and `lca.py` (DOL data).

| Level | Meaning | What can produce it |
|---|---|---|
| **A** | Role-level support stated | A quote from the posting itself ("visa sponsorship is available") |
| **B** | Employer history found; role unconfirmed | Exact legal-name match in imported DOL LCA disclosure data |
| **C** | Indirect or third-party only | Community-list sponsorship tag; LCA filer whose name is only similar |
| **D** | Posting rules it out | "will not sponsor", citizenship / permanent residency / clearance required, permanent work authorization required, OPT/CPT excluded |
| **U** | Unknown | Nothing credible either way |

Precedence: D, then A, then B, then C, then U. A refusal in the posting always wins over
employer history, and the conflict is recorded. A third-party "does not sponsor" tag against
an employer with LCA history stays Level B but is flagged as contradictory.

Every stored assessment (`job_verdict.sponsorship_json`) carries: evidence items (scope,
claim, source name, source URL, quote, date observed), what is still unknown, contradictions,
and the question to ask the recruiter. There is no numeric probability anywhere.

## Importing LCA data (needed for Level B)

1. In a browser, open https://www.dol.gov/agencies/eta/foreign-labor/performance and download
   the newest "LCA Programs (H-1B, H-1B1, E-3)" disclosure file, for example
   `LCA_Disclosure_Data_FY2026_Q3.xlsx`. The site blocks scripted downloads, so this step is
   manual. Files are cumulative within a fiscal year, so the latest quarter is enough.
2. `careeros lca import ~/Downloads/LCA_Disclosure_Data_FY2026_Q3.xlsx --fiscal-year 2026`
   (large files take several minutes). Optionally import the previous fiscal year too.
3. `careeros discover --no-fetch` re-evaluates stored jobs with the new evidence.

Only certified cases are counted. Per employer and fiscal year the system keeps totals, new
employment, the count in analyst / data / business occupations, common job titles and
worksite states.

## Limits, stated plainly

- LCA history is historical and employer-level. It does not show that a team, role, location
  or hiring cycle will sponsor, or that new graduates on F-1 OPT are considered.
- Identity: filings are attributed only on an exact normalized legal-name match. "State
  Street" versus "State Street Bank and Trust" is reported as a possible match and capped at
  Level C until a confirmed alias mechanism exists (planned).
- Pattern matching reads common wording. Unusual phrasing lands in U with an
  "ambiguous wording" note, never in A.
- Nothing here is legal advice. Work-authorization facts (OPT dates, STEM OPT eligibility)
  must be confirmed with the BU ISSO or immigration counsel.
