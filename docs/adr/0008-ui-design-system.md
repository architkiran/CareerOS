# ADR 0008: UI design system

Status: Accepted

## Context
Nine phases of pages had grown a crowded top bar of 11 links, all-caps table headers and identical cards everywhere. The dashboard must stay offline-capable under a strict `default-src 'self'` Content Security Policy.

## Decision
- Grouped left sidebar (Pipeline, Insight, Setup) with `aria-current`; collapses to a scrolling strip under 860px.
- One typeface, IBM Plex Sans, bundled in `web/static/fonts` (SIL OFL, licence included) so it works offline and under the CSP. Tabular figures everywhere; sentence-case headers.
- Ledger palette (cool paper, ink, slate-blue accent). Green, amber and red are reserved for pass, review and fail meaning; light and dark themes.
- The score meter is the one distinctive element: the fill shows the score in its eligibility colour, and a hatched tail shows how much of the weighted information was unknown.
- No inline `style`/`script`/event attributes (a test enforces this). Numeric widths use generated value classes (`.v0`-`.v100`, `.c0`-`.c100`) rather than inline styles, which a strict CSP would silently block.
- Job page: reading column plus a sticky action rail; inbox hides less-used filters behind *More filters* (auto-open when active).
- Visible focus rings, skip link, reduced-motion support, no horizontal scroll at 390px.


## CareerOS 2.0 amendment

The user's product brief supersedes the system-theme default: use charcoal dark
surfaces first and an explicit persisted light-mode toggle. Retain the local font,
semantic status colors, strict CSP, responsive sidebar and visible focus states.
Mission Control uses real agent progress and result summaries rather than decorative
charts. The existing Overview and all previous routes remain available.
