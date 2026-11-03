# ADR 0004: SQLite before PostgreSQL

Status: Accepted

## Context
One user and zero budget. Hosted databases add cost and operational burden.

## Decision
Use SQLite WAL with SQLAlchemy and Alembic. Keep database access behind repositories/services to allow migration later.

## Consequences
Very low cost and simple backups. Revisit if concurrent writes or remote multi-user access become real requirements.
