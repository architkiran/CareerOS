# Evidence workbench and source monitoring

This update preserves the Python/SQLite architecture and the three primary
workspaces. It adds contextual tools inside applications rather than another
collection of unrelated product pages. The branch is
`feature/careeros-evidence-workbench`, based on `79a592a`.

## Resume repair and editing

The old generator rebuilt content from an incomplete profile, capped experiences
at two, and previously sliced the project list before later selection. The supplied
LaTeX master contained detailed work and project evidence that never reached the
profile bank. The repair imports the explicitly user-authored master as data, with
a source hash; it does not execute imported TeX commands or treat comments as facts.
Optional, unbuilt bullets are excluded. Re-importing the same master is idempotent.
Existing IDs and unrelated profile items are retained.

The current local library has three verified experiences, ten verified projects,
44 verified skills, and one additional project awaiting verification. Two master
experiences now retain all six substantive source bullets. The conflicting
Payments & Interchange metrics remain unverified because an earlier user statement
said numbers were pending, although the analyst PDF contains numbers. That project
is visible in the workbench but cannot be included until verified.

Open an application and choose **Open tailoring workbench**. It provides:

- The posting's explicit tool mentions mapped to verified skills and project evidence.
- A professional summary assembled from supported evidence and relevant skills.
- All verified experience bodies, editable without modifying master facts.
- Project choices from the entire verified library, including projects outside the
  automatic shortlist; checked projects are pinned to that revision.
- Verified skill choices, initially focused on JD mentions, selected-project tools
  and role-relevant core skills, rather than dumping every skill into the PDF.
- An original-summary reference, saved feedback requests, immutable PDF revisions
  and existing text diffs. Stale version submissions are rejected.
- A local image of the actual PDF, avoiding embedded-browser PDF plugin failures;
  full PDF downloads retain `Archit_Kiran_Kumar_Resume.pdf`.

Default preparation retains all verified experiences and selects four projects.
The master preamble, typography, geometry and section/entry styling remain fixed.
Education entries retain aligned dates, and skill groups follow the master layout.
No automatic fitting operation silently deletes bullets or shrinks the typography.
Page count, overflow, paper size, missing experience content, omissions, underfill,
claim evidence and binary integrity are checked before approval. Missing facts
remain warnings or errors. Existing document versions remain available.

Feedback is a saved request, not an unverified fact and not a claim that a model
has applied it. Use the content controls to apply changes. Edits introducing new
terms or metrics outside the selected evidence are rejected; substantial factual
additions belong in the verified profile. This conservative editing workflow is
not unrestricted semantic rewriting or a claim of perfect tailoring. Ollama remains
optional; no paid provider was enabled.

## Agents and networking

Three runnable specialists were added to the existing durable orchestration:

1. **Application evidence mapper** saves a private requirements/evidence brief.
2. **Networking researcher** saves published recruiting leads, source excerpts,
   company-specific email and LinkedIn drafts, and targeted search handoffs.
3. **Freshness monitor** checks due feeds, persists changes and queues rescoring.

Starting an application queues the first two agents automatically. Networking can
also be refreshed in the workbench. Existing applications received real saved briefs
in live validation. There is no universal free hiring-manager directory behind this
feature. A posting with no appropriate recruiting contact produces no invented
person or guessed email. Accommodation, support, privacy and scam-report addresses
are excluded. Search links are research handoffs; identities and recipient purpose
still need review. No contact was messaged and no application was submitted.

## Freshness and coverage

Discovery now links to **Monitoring & new roles** (`/watch`). The local monitor has
been enabled in the current environment. It checks at most five due feeds per
mission and respects configured gaps and provider floors: employer feeds at least
15 minutes, SmartRecruiters and WWR at least an hour, Jobicy at least an hour,
Remotive at least six hours. It runs only while the local server/worker runs. Sleep,
network delays and large feed retrievals can delay checks. These are conservative
polling intervals, not a promise of instantaneous delivery.

“Found today” means first observed locally. Publication filters (one minute, one
hour, 24 hours) require a source publication timestamp within that window; missing,
old and future timestamps cannot pass because a listing was imported today.
Greenhouse update times are not publication dates. Ashby may report republishing.
Remotive itself delays listings by 24 hours. The watch page shows cadence, last
attempt, next due and provider timestamp limitations; matching-role alerts refresh
locally every five seconds and can be marked reviewed.

The explicitly reusable We Work Remotely RSS was added with original-link
attribution, secure XML parsing, request/size limits and a minimum hourly gap.
Window absence does not close saved jobs. Its live check accepted 99 of 100 items;
one malformed item was isolated. Fivetran's direct employer feed imported 158 jobs.
The first scheduled freshness mission checked five feeds and found four more jobs.
LinkedIn and Handshake remain user-assisted because account scraping is restricted.
Himalayas, USAJOBS authentication and broader availability checks were researched,
not implemented as if they were already connected.

## Research and validation

Read [the cited research report](../reports/CareerOS%20evidence%20and%20discovery.md)
for Tsenta, Teal, Huntr, Simplify, OpenResume, YAMLResume, RenderCV, JobCtrl and other
references. It distinguishes recommendations from delivered functionality and
commercial/source-available products from OSI open-source software. No reference
code, branding or assets were copied.

The baseline passed 621 tests. The updated full suite passed 634 tests; Ruff and
strict mypy passed. New tests cover master preservation/comments/idempotence,
non-destructive editing, feedback persistence, unsupported edits, source timestamp
filters, provider cadence and scheduling deduplication, real support-agent handoffs,
contact evidence, safe RSS parsing, lower-ranked pinned projects and private PNG
previews with integrity checks. Offline route tests use a small PDF compiler stand-in;
separate live checks use real cached Tectonic compilation and rendered inspection.
Four existing draft applications were regenerated as one-page PDFs. Review warnings
were not acknowledged automatically. A before-import backup was created, and the
final backup includes master sources, documents, private briefs and feedback.

The PDF preview uses [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/python_api.html)
locally, guarded by a mutex because PDFium does not support concurrent calls across
threads. No candidate resume data is sent to a hosted renderer.
