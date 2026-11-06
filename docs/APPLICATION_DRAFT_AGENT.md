# On-demand application draft preparation

An existing application in `preparing` or `ready` can request **Prepare both
template drafts with agent**. This starts a durable, target-scoped mission visible
in Mission Control and `/agents/application`, with persisted attempts and retries.
Duplicate active requests reuse the mission. Completed runs may be requested again;
unchanged intact document versions are reused.

The worker reads verified profile items and the saved posting, generates the
existing deterministic resume and cover-letter templates, runs their claim QA,
verifies both artifact hashes, and links the exact immutable document versions.
The application workspace is the review handoff. No claims from PDF references
are promoted to verified facts. New requirements in a job description cannot add
candidate qualifications.

This is template draft preparation, **not exact master-resume tailoring**. Every
run carries that warning, and the application workspace links to original PDF
references for comparison. Warnings are not acknowledged automatically. The agent
cannot create, approve or use an approval, submit an application, send a message,
or answer legal/work-authorization questions. Submission remains user-performed.

The configured private data directory is injected by the server/CLI worker, never
accepted as a task input. A missing directory configuration fails safely. The
task's target must match its mission, and an application that progresses beyond
preparation is not modified. Existing career-review and interview workflows retain
their own scope and histories.

Tests cover target isolation, CSRF, state changes, missing configuration, private
metadata, rollback, duplicate requests, immutable reuse, artifact downloads and
the absence of automatic approvals or submission.
