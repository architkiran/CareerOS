# On-demand interview practice

Interview practice is a bounded specialist requested from a job detail page or
`/interviews`. It is not a recurring task for every discovered job. Preparation
runs use the existing durable mission/attempt machinery, including deduplication,
retries, cancellation and persisted artifact links.

Migration 0013 adds private `interview_plan` and `interview_answer` tables. A plan
stores immutable questions, posting description hash, verified-profile evidence
hash and preparation context. Repeated unchanged inputs reuse the plan and preserve
answers; changed verified evidence creates a new plan. Answer edits and feedback
are private local state. They never update verified facts or application outcomes.

## What is actually generated

- Role/motivation practice tied to the saved job title and employer.
- Up to four technical topics explicitly mentioned in the posting, selected from
  a controlled question catalog (SQL, Python, Kafka, AWS, BI, Excel, PySpark,
  statistics). Hypothetical exercises are not statements about candidate history.
- Questions naming up to two relevant verified projects, with source references.
- An experience discussion grounded in an existing verified employer reference.
- Business-domain preparation and questions to ask the team.
- Optional context explicitly labelled as user-provided historical feedback.
- A role-family PDF reference link when a corresponding reference exists. Its raw
  claims are not imported into question grounding or marked verified.

Missing/unverified skills are labelled as learning topics, not claimed expertise.
Project benchmarks are not copied into prompts. Employer-facing facts are not
invented, and posting text has no instruction/tool privileges.

## Practice and feedback

Each prompt includes a review checklist, a private answer, optional reflection and
an explicitly self-assessed confidence rating. This is **not an AI grade**, an
employer-supplied question set, or a certification of interview readiness. All
questions need saved answers plus explicit confirmation before practice can be
marked complete. Editing an answer reopens the practice.

Feedback notes record what the user actually received or interpreted; no application
status is changed automatically. Activity events contain only IDs/counts and generic
messages, never answer or feedback text. Forms are CSRF-protected and pages use
no-store cache headers. No email, messaging, application or profile-write tool is
available to the preparation agent.

## Operation and limits

`/agents/interview` shows the specialist's allowed tools and run history. Mission
pages link to the exact saved plan, rather than a changing latest-result page.
Market-agent runs now also link to their exact saved brief.

The feature works without a model. Local Ollama was unavailable during validation,
so no model-assisted feedback is claimed. Rich conversational mock interviews,
automatic solution grading and voice practice remain future capabilities.

The full suite at this milestone: **550 tests passed in 30.07 seconds**, with Ruff,
formatting and strict mypy clean. Tests cover evidence grounding, unverified claim
exclusion, idempotence, profile-change versioning, private logs, answer editing,
completion gates, CSRF/escaping, on-demand missions and artifact linkage.
