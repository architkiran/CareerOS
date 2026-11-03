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
