# ADR 0007: Deterministic matching, algorithm `match-v1`

Status: Accepted

## Context
PRODUCT_SPEC.md requires hard filters separate from an explainable 0-100 score, configurable weights per lane, no opaque model score, and that missing salary must not become zero and unknown sponsorship must not count as available.

## Decision
- **Hard filters** (posting status, employment type, excluded title terms, lane title exclusions, inferred seniority, location/relocation, work-authorization statements in the posting) each return pass / fail / unknown with a reason and, where relevant, a quoted excerpt. Overall eligibility is fail if any filter fails, otherwise unknown if any is unknown.
- **Seniority** is inferred from title words and "N+ years of experience" phrases, always with a confidence and rationale, and only fails a job on high confidence.
- **Work authorization** uses only what the posting says and the user's *confirmed* answers. An unstated policy is unknown, never pass or fail. Citizenship or clearance requirements are never auto-passed.
- **Score**: seven dimensions with the lane's weights. Each dimension is scored 0-1 from explicit data; a dimension with no information counts as **neutral (0.5)**. `completeness` is the share of weight backed by real information and is shown next to every score.
  - We first tried excluding unknown dimensions and renormalising. Tests showed a thin posting (e.g. title match + remote only) could then score 100 at 30% completeness and outrank well-described roles, so we moved to neutral.
- **Only verified** profile skills, experience and projects count; unverified ones are reported as not counted.
- **Reproducibility**: inputs are frozen dataclasses hashed with the algorithm version; unchanged inputs are not rescored.
- **Overrides** (eligibility and/or score, with a required reason) live in a separate table, win over computed values, survive rescoring, and the computed result stays visible.

## Consequences
Scores are explainable line by line and testable. Changing any rule requires bumping `ALGORITHM_VERSION`, which rescores everything on the next pass.

## Amendment: `match-v2` (2026-11-03)
Greenhouse's list API never states employment type, so every Greenhouse job was "unknown" on that filter and none could pass. v2 reads an *explicit* statement from the posting text ("this is a full-time position", "6-month contract role", "contract-to-hire", "internship program") and quotes it as evidence. If only allowed types are mentioned the filter passes; if a disallowed type is mentioned it stays unknown (never an inferred fail); if nothing is stated it stays unknown. "Full-time equivalent" is ignored. Stored v1 scores are rescored automatically when the worker starts.

Also in v2: a location that names only non-US places (e.g. "Toronto", "Singapore", "EMEA") fails the location filter, since the target is US roles; a location naming any US place is never failed. And when the posting says nothing about sponsorship but the user's *confirmed* answer is that they don't need it, the work-authorization filter passes, because the policy doesn't affect them. If they do need sponsorship, a silent posting stays unknown until employer research (Phase 5) resolves it.
