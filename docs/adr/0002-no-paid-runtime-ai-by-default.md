# ADR 0002: No paid runtime AI by default

Status: Accepted

## Context
The user has Claude Pro/Claude Code but wants no additional spending. A Pro subscription must not be assumed to include API credits.

## Decision
Core features use deterministic code. Model gateway is optional, disabled by default, and supports local inference first. Paid API use requires explicit user configuration and budget approval.

## Consequences
Some language-generation quality may be lower without an API model. Cost remains predictable and the application never silently incurs charges.
