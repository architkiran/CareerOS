# First-slice validation

Baseline `b95223c`: 476 tests passed in 23.40 seconds; Ruff, format and strict mypy passed.
Final feature code `da85224`: **501 tests passed in 25.16 seconds**.

Commands ran from the isolated feature checkout, using the original checkout's
already-installed Python 3.12 environment (pytest resolves this checkout's `src`):

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
node --check src/careeros/web/static/mission.js
node --check src/careeros/web/static/theme.js
git diff b95223c --check
```

- Ruff: all checks passed.
- Formatting: 173 files already formatted.
- Strict mypy: no issues in 100 source files.
- Both new JavaScript files passed syntax validation.
- Migration/model metadata matches; full downgrade/re-upgrade tests pass.
- Prior profile/operation rows survive migration 0011 and downgrade unchanged.
- Mission start rollback leaves no orphan mission, agent or task rows.
- Concurrent starts create one five-step graph.
- Tested real fixture ingestion through the orchestration path, scoring, analytics,
  healthy completion and degraded setup/partial-data outcomes.
- Tested failed feeds, bounded retries, manual recovery with preserved attempts,
  blocked dependencies, pause/resume, cancellation during execution, crash reclaim,
  stale-owner fencing, invalid outputs, privacy-safe failures, scheduling, CSRF,
  escaped summaries and legacy retry routing through the mission gate.
- A healthy mission preserves the verified profile export unchanged.

## Browser verification

Used a separate scratch database and a loopback-only server. The actual browser
rendered Mission Control in dark mode in a narrow viewport. Clicking **Run career
review** created a persisted mission. The worker completed all five steps; after
refresh the browser displayed each result, all dependencies, and a degraded review
with truthful missing-source/profile warnings. Live polling showed connected state.
No real jobs or candidate data were fabricated for this preview.

Headless Chrome was blocked by the environment. The built-in browser later lost
debugger synchronization while testing additional viewport sizes and saving
screenshots. Therefore desktop/mobile screenshots, light-mode visual checks and a
full browser accessibility audit are **not claimed as verified**. No screenshot
artifact was saved. Route rendering, CSP/no-inline checks and the existing browser
form tests passed in the automated suite.

No live ATS feeds or Ollama inference were contacted during validation. Adapter
network responses were mocked from the existing fixtures. Runtime model services
remain optional, and paid services were not enabled. Docker was not rebuilt.

## Review safety

All changes are on a feature branch in an isolated local clone. The Desktop main
checkout, personal database, documents, source watchlist and ignored configuration
were not altered. The branch was not pushed or merged. A patch and verified Git
bundle make the implementation reviewable and portable.

A final populated-data assertion also renders Mission Control after fixture-backed
agent discovery/matching. This confirms job cards, source dates, first-seen times
and last source refresh render with nonempty data. The agent and Mission Control
suites passed together: **23 passed in 2.20 seconds**. No runtime code changed
after the 501-test full-suite run.
