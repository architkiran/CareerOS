# Freshness correction — 10 November 2026

The corporate-development example was stored from Jobicy with `pubDate`
2026-11-07. This is not evidence of the employer's original publication date.
The October 2 date supplied by the user was not independently verified without
an identified employer listing. We must not reconcile those as the same event.

Changes:
- Publication-age filters now require `publication_kind=original`.
- New Jobs includes a Verified last 24 hours view. Aggregator publication,
  republish, source creation, future and unknown dates cannot qualify.
- Cards show original publication as unknown for other date types; their exact
  provider date/semantics remain in expandable evidence.
- “New” discovery badges now say “First found since your visit.”
- Corporate-development analyst roles with cold-calling duties no longer match
  unrelated analyst lanes; explicit corporate-development lanes remain supported.
- Matching version v9, rescored existing jobs. No profile facts were changed.

765 tests pass, including two date regressions and the added outbound-sales
labeled case (23 labeled cases total). Lint and strict type checks pass.
The strict view may be empty. That is preferable to representing old listings
as fresh. This does not certify every date or establish adequate market coverage.

Official field semantics: https://docs.greenhouse.io/job-board
