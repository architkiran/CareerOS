# ADR 0006: Plain JavaScript for live updates instead of HTMX (for now)

Status: Accepted

## Context
The README suggests HTMX plus minimal Alpine.js. Phase 3 needs a live activity feed and refreshing stats. The dashboard sends a strict `Content-Security-Policy: default-src 'self'`, must work offline, and has no Node build step. Loading HTMX from a CDN would break the CSP and offline use; vendoring it was not possible from the build environment.

## Decision
Use one small same-origin script (`web/static/app.js`, ~100 lines) that:
- subscribes to `/events/stream` (SSE) with `Last-Event-ID` resume;
- falls back to polling `/events/feed` every 5 seconds after repeated SSE errors or when EventSource is unavailable;
- inserts event text only via `textContent`;
- refreshes the server-rendered, escaped `/partials/overview` fragment after pipeline events.

Forms remain plain HTML posts with redirects, so every page works without JavaScript.

## Consequences
No third-party script, CSP stays `'self'`, works offline. If UI interactions grow, vendor `htmx.min.js` into `web/static/` and adopt it incrementally; the server-rendered partial endpoint already fits that model.
