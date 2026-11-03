# ADR 0001: Local-first modular monolith

Status: Accepted

## Context
One user, strict zero-dollar target, limited engineering time, personal data sensitivity, and a need to iterate quickly.

## Decision
Use one Python modular monolith, SQLite, a local task queue, and a server-rendered dashboard. Cloud deployment is optional later.

## Consequences
Low cost and operational complexity. Less suitable for many concurrent users, but that is not the current problem. Revisit only with measured evidence.
