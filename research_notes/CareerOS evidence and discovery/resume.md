# Truthful resume tailoring and editing

## How should master content and layout be preserved?

### Takeaway
The master must remain an immutable, inspectable source with mapped content slots, rather than a preamble attached to a sparse resume rebuilt from profile rows. This is an architectural recommendation inferred from mature content/layout separation, not a claim that reviewed tools preserve arbitrary LaTeX perfectly.

### Cited Findings
- YAMLResume separates content, schema validation and output presentation; layout configuration is distinct from content. — [Repository](https://github.com/yamlresume/yamlresume); [Layout documentation](https://yamlresume.dev/docs/layouts)
- RenderCV offers versionable text content, schema validation, configurable presentation and watch mode. Its currently documented output is Typst/PDF, not a drop-in LaTeX master patcher. — [Repository](https://github.com/rendercv/rendercv); [CLI guide](https://docs.rendercv.com/user_guide/)
- OpenResume provides live PDF updates, local browser operation and PDF import. Its parser explicitly targets English single-column resumes and uses heuristic text, line and section grouping. — [Repository](https://github.com/xitanggg/open-resume); [Parser documentation](https://www.open-resume.com/resume-parser)
- LatexWalker models snippets as nodes with source positions and supports custom macro definitions; it explicitly is not a complete LaTeX engine. — [pylatexenc documentation](https://pylatexenc.readthedocs.io/en/latest/latexwalker/)
- Resumake main currently serves a retired-app/static page; original application source remains on v2. Do not present historical functionality as the current main-branch implementation. — [Repository](https://github.com/saadq/resumake.io)

### Inferences
- Keep the full user-supplied master, hash and baseline PDF. Map summary, experience, project and skills slots once. Lock macros, margins, typography, identity and dates. Patch escaped content, rather than asking a model to regenerate TeX.
- Retain every master experience and its substantive bullets by default. Missing profile mappings must be visible; preserve imported evidence as reviewable source material without silently promoting it into verified candidate facts.
- Show a completeness inventory: master and mapped experience counts, bullet counts, full project library, missing mappings and unverified exclusions. A one-page PDF can still be a failed half-empty resume.
- Separate the full project library from the 2–4 projects on one exported version. Rank all verified projects, show reasons and omissions, and permit pin/exclude controls. Evaluate explicit requirements, domain, outcomes and evidence strength alongside keywords. Preserve in-progress status.
- The current code has concrete truncation causes: generate defaults experience_limit=2, plan slices experiences, builder limits experience paragraphs to three and projects to four before further filtering. The summary is education plus matching skills. More model calls cannot recover data absent from the candidate representation.

### Gaps
- No reviewed source guarantees mapping of arbitrary custom LaTeX or a universal ATS score. CareerOS must validate its known master and flag unsupported constructs.
- No public evidence proves a project-ranking formula guarantees interviews.

## How can wording change without fabrication?

### Takeaway
Build requirement-to-evidence plans and structured edit proposals. Local inference may suggest wording, while independent validation, coverage gates and user review control whether it becomes an application artifact.

### Cited Findings
- Ollama accepts JSON Schema in the format parameter and documents validating the returned data with Pydantic. This controls response structure, not factual correctness. — [Structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- JSON Resume defines structured work, education, skills, projects and extensions, plus schema validation. It is an inventory/interchange pattern, without candidate verification semantics. — [Schema](https://jsonresume.org/schema)

### Inferences
- A requirements agent extracts responsibilities, required/preferred skills, seniority and domain, retaining excerpts. Distinguish explicit statements from inferred themes.
- An evidence agent maps each requirement to verified project outcomes or experience bullets, marking supported, partial and missing. Missing technologies remain gaps instead of appearing as candidate skills.
- An optional local wording agent returns typed patches: target claim ID, old text, proposal, evidence IDs and rationale. JD text is untrusted context. New metrics, dates, employers, credentials, tools, ownership and work-authorization statements are forbidden without verified backing.
- Validate proposed named entities, skills and metrics against referenced evidence. Schema-valid wording may still change meaning; a syntax or keyword pass is not semantic proof. Unsupported changes remain proposals or are rejected.
- With no local model, label the fallback honestly as selection/reordering, and retain complete master wording. Do not imply a professional rewrite or derive unprovided expertise/duration.
- Agents should persist concrete artifacts: requirement map, evidence coverage, proposed edits and QA report. Handoffs should reference artifact IDs and input hashes.

### Gaps
- No schema proves paraphrase entailment. Model-based entailment also fails; perfect automatic tailoring is not an honest guarantee.
- Local model availability, hardware capacity and quality were not benchmarked here; check the actual environment before promising performance.

## What editing UI and QA make it trustworthy?

### Takeaway
Use a compact content workbench with requirement evidence, section-level edits, versioned suggestions and PDF preview. Make omissions and unresolved gaps visible before download or approval.

### Cited Findings
- OpenResume updates its PDF as fields change, providing direct edit-to-output feedback. — [Repository](https://github.com/xitanggg/open-resume)
- RenderCV produces PDF, source, per-page PNG, Markdown and HTML artifacts and documents automatic re-rendering; this supports textual and visual inspection patterns. — [CLI guide](https://docs.rendercv.com/user_guide/)

### Inferences
- Prefer Requirements, Content and Preview tabs with a stable role/company/version header and one primary regenerate action.
- Provide editable summary and experience bullets, project pin/exclude controls, and per-section feedback such as “keep Spark” or “emphasize reconciliation.” Persist feedback, show the resulting diff, and surface requests lacking evidence.
- Accept/reject/reset suggestions individually. Store immutable parent version, master hash, selected evidence, feedback, content hash and artifact hash. Changes invalidate prior approval snapshots; never overwrite approved/submitted packages.
- Coverage QA should flag missing master experiences, empty experience bodies, missing required sections and unexpected word/bullet reductions. Meaningful omission needs explicit user intent; a tunable reduction threshold is a warning, not a universal quality score.
- Layout QA checks extracted expected content and geometry, not merely page count: identity, section labels, selected items, overflow, margins and unexplained underfill. Render final pages and inspect a real resume. Do not inflate type or invent content to fill whitespace.
- Regression cases: all master experiences retained; different JDs selecting different supported projects; unknown skills remaining gaps; pin/exclude round trips; feedback surviving reload; compiler failure preserving the previous version; fabricated metrics blocked.

### Gaps
- ATS-friendly/perfect-typography claims are project descriptions, not independent guarantees for every employer system. Report concrete checks instead of a misleading perfect score.
