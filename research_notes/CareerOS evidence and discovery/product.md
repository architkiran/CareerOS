# Career product workflows and interface patterns

Research checked 2026-11-06. Scope: primary product/help pages and public repository documentation. Findings describe documented capabilities, not independently audited performance. No accounts, purchases, installations, code copying or real applications were used. Commercial products are workflow references, not proposed runtime dependencies.

## What should CareerOS learn from established products and job boards?

### Takeaway
The strongest pattern is a comprehensive base resume connected to a job-specific review workspace with editable suggestions, visible differences and contextual networking. Product polish comes from resolving the current decision in one place rather than adding another destination for every capability.

### Cited Findings
- **Tsenta** documents Find/Prep/Apply/Track stages, a match feed and separate controls for resume review, form review and automatic applications. Its coverage and speed assertions are vendor claims, not independent verification. CareerOS can adapt clear progression without automatic submission. — [Tsenta workflow](https://help.tsenta.com/how-tsenta-applies-to-jobs)
- Tsenta resume review includes highlighted differences, a change summary, direct editing, chat beside the resume, use-original choice and persistent preferences when requested. It supports separate resume profiles by role. Its documented Aggressive mode can stretch claims, which conflicts with CareerOS truthfulness; do not reproduce that mode. — [Tsenta tailoring and diff](https://help.tsenta.com/resume-tailoring-and-cover-letters)
- **Teal** documents a comprehensive bullet bank per position, per-resume toggles, reordering and inline editing. Editing shows counts, save/cancel and an explicit save-to-all-resumes checkbox. This clearly separates editing one tailored copy from modifying reusable source content. — [Teal bullet editing](https://help.tealhq.com/en/articles/14435954-how-to-edit-resume-bullets-in-teal)
- **Huntr** distinguishes comprehensive base resumes from tailored copies. Editor, Layout & Style, Templates and Score tabs separate content from presentation. Base scoring evaluates completion, content quality and length; tailored scoring evaluates job alignment. These are vendor heuristics, not guarantees that any ATS will accept a resume. — [Huntr builder](https://help.huntr.co/en/articles/12824077-understanding-huntr-s-resume-builder)
- Huntr describes comparing a posting with the resume, then applying, editing or customizing suggestions. It recommends reviewing the base before tailoring it. — [Huntr review and tailor](https://help.huntr.co/en/articles/11535512-ai-review-ai-tailor-walkthrough)
- **Simplify** embeds Get referrals in each job/application, avoiding a disconnected network page. Its documentation says possible connections are not confirmed referrals or proof of hiring involvement; relationship/employment data can be stale. Drafting is separate from sending. — [Simplify referrals](https://help.simplify.jobs/help/articles/4158996-find-referral-connections-with-simplify)
- **Welcome to the Jungle** describes matching profile evidence, preferences and company aspirations, plus list, save and details views. Its proposed why-this-match agent remains labelled forthcoming in the inspected article; do not call it verified deployed functionality. — [Matching explanation](https://help.welcometothejungle.com/en/how-does-the-matching-algorithm-work)
- Its help describes desktop-side/mobile-bottom filters and following employers for new-posting notifications, even when a role does not match current preferences. This separates employer watching from recommendations. — [Following employers](https://help.welcometothejungle.com/en/if-im-getting-fewer-results-how-can-i-make-sure-im-not-missing-anything-how-can-i-broaden-my-selection)
- **Wellfound** distinguishes employer-provided salary from computed estimates with explicit labels. Missing salary remains missing when evidence is insufficient. This provenance pattern is valuable for timestamps and sponsorship too. — [Wellfound salary provenance](https://help.wellfound.com/article/774-salary-data-and-estimates)

### Inferences
- Build a job workbench with connected JD requirements/evidence gaps, editable sections/selections and actual PDF preview. A two-column implementation can place requirements in collapsible details above the editor.
- Show base-versus-selected counts for experiences, bullets, projects and skills. Block silent export if an experience loses all bullets or content collapses relative to the master. Preserve all experience by default.
- Separate factual coverage and layout health from keyword fit. Avoid a universal ATS score.
- Put contact relevance, evidence, last-checked date, relationship status, public URL and editable draft inside each application. Unsupported guessed emails or fictitious referrals destroy trust.
- Retain the warm neutral brand and three primary destinations. Add contextual workflows through tabs/disclosure, not a growing sidebar.

### Gaps
- Vendor accuracy, indexing counts, speed and interview conversion were not tested.
- Private authenticated screens were not operated; interface descriptions come from public documentation.
- A local app cannot reproduce proprietary job/contact indexes for free. It needs explicit supported-source scope and user-assisted evidence import.

## Which additional source projects offer architectural and UI ideas?

### Takeaway
Five additional projects provide useful interaction patterns. Their licenses, provider defaults and access policies differ; borrow concepts while retaining CareerOS's architecture and boundaries.

### Cited Findings
- **OpenResume** (`xitanggg/open-resume`, AGPL-3.0 shown by GitHub) documents a browser-local editor whose PDF updates with changes, PDF import and a parser inspection tool. Its ATS and hiring-success statements remain project claims. Adapt edit/preview and PDF extraction checks. — [OpenResume](https://github.com/xitanggg/open-resume)
- **JobCtrl** (`ebarti/JobCtrl`, AGPL-3.0) documents requirement-level scoring, fact-linked resume bullets, validation against invented metrics/dates/titles/employers, exact-version review and availability rechecks that retain descriptions. It also documents paid/provider dependencies and default discovery without robots checks; those defaults do not fit CareerOS. — [JobCtrl](https://github.com/ebarti/JobCtrl)
- Its design document specifies restrained timetable-inspired visual language, semantic statuses and compact typography. This demonstrates an operations UI does not require decorative activity animation. — [JobCtrl design](https://github.com/ebarti/JobCtrl/blob/main/DESIGN.md)
- **Job Search Terminal** (`uxdesignlab/job-search-terminal`) documents guided role lanes, resumes by direction, location preferences, materials, company research and interview preparation. Ollama is supported; optional services use external keys. Its CC BY-NC license makes source-available a more accurate description than OSI-open-source. — [Job Search Terminal](https://github.com/uxdesignlab/job-search-terminal)
- Its design guide favors compact calm scanning, flat bordered panels, reusable primitives, status text alongside color, keyboard focus and reduced-motion support. It discourages oversized marketing heroes and nested decorative cards. — [Design system](https://github.com/uxdesignlab/job-search-terminal/blob/main/docs/design-system.md)
- **Jobtra** (`CU1KNIGHT/Jobtra`) documents local FastAPI/SQLite/plain HTML-JS, application stages, original-posting reparsing, documents and email classification. A broad workflow can remain cohesive in a small stack. — [Jobtra](https://github.com/CU1KNIGHT/Jobtra)
- **The Remote & Ledger** (`dark-matter08/remote-ledger`, MIT) presents a local tracker with newspaper-inspired identity, job profiles, inspectable matching and guided progression stopping before submission. Its chosen AI runner can use subscriptions/API keys; local-first does not imply free inference. — [Remote Ledger](https://github.com/dark-matter08/remote-ledger)

### Inferences
- The defects concern incomplete ingestion, destructive selection, missing feedback and freshness semantics. They do not establish a need for a new frontend framework.
- Use existing orchestration for specialized runs. New persistence should serve user feedback, watchlists, monitor state and actionable notifications.
- Add a layout/coverage agent. A compiled one-page PDF that silently lost content is a failure.
- Retain source snapshots and resume versions; regeneration must never replace approved artifacts silently.

### Gaps
- Repositories were not installed or benchmarked. README/design claims do not establish production reliability.
- No code/assets were copied. License observations are not permission to redistribute implementations.

## Which agent jobs and interface priorities improve CareerOS most?

### Takeaway
Agents should own observable useful outputs. Prioritize master-resume coverage, constrained tailoring, feedback, freshness verification and networking briefs over additional names or simulated activity.

### Cited Findings
- Source-preserving editing patterns: [Tsenta diff](https://help.tsenta.com/resume-tailoring-and-cover-letters), [Teal bullet bank](https://help.tealhq.com/en/articles/14435954-how-to-edit-resume-bullets-in-teal), [Huntr base/tailored distinction](https://help.huntr.co/en/articles/12824077-understanding-huntr-s-resume-builder).
- Contextual contact uncertainty: [Simplify referral flow](https://help.simplify.jobs/help/articles/4158996-find-referral-connections-with-simplify).
- Availability/provenance patterns: [JobCtrl](https://github.com/ebarti/JobCtrl), [Wellfound labels](https://help.wellfound.com/article/774-salary-data-and-estimates).

### Inferences
- **Master resume auditor**: inventory every experience/project/skill; identify imported, verified, incomplete, conflicting and role-variant content. Never auto-verify extracted claims.
- **JD evidence analyst**: map stated requirements to verified evidence, adjacent evidence and missing information, with candidate record references.
- **Tailoring editor**: retain master experience and factual bullets by default; select projects transparently; adapt wording/summary within evidence; expose alternatives.
- **Layout/coverage verifier**: compare selected sections, bullet counts, extracted PDF text and page utilization with the master. Detect overflow and destructive underfill without inventing filler.
- **Feedback agent**: turn keep BU Spark, use fraud detection, shorten summary or restore a bullet into reviewable changes. Separate one-time instructions from lasting preferences. New unsupported skills become pending profile facts, never silent qualifications.
- **Source monitor**: compliant per-source polling with last-success, next-due, delay, backoff and outage state. Deliver local new-role notifications. Minute-level promises require permitted frequency and sufficient timestamp evidence.
- **Freshness verifier**: distinguish source-published, source-updated, first-observed and last-checked. Discovered today does not mean published today; preserve unknown timestamps and source-supported repost indicators.
- **Networking researcher**: use permitted public evidence and user-owned/imported contacts for application briefs. Offer research links when no evidence exists. Draft cold email, connection note and follow-up; never guess identity/email or send automatically.
- **Next-action coordinator**: surface actionable exceptions and useful completed work. Separate Needs you, Working and Recently completed; expose actual descriptions, last-update/elapsed time, retries and artifacts.
- **Order**: repair complete master ingestion/retention, then edit/feedback, then honest monitoring/freshness, then networking breadth. Additional agents amplify errors if these foundations remain broken.

### Gaps
- Implementation scope depends on repository audit and tests by the parent engineer.
- A draft does not establish a recipient's identity, email, employment or hiring involvement. Paid enrichment, universal scraping and automatic sends remain excluded.
