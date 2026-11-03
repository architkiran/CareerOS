# First prompt for Claude Code

Read `CLAUDE.md` and all docs under `docs/`. Do not implement the entire system at once.

First inspect the repository and report:
1. what already exists;
2. a proposed final file tree;
3. the smallest runnable Phase 0 plan;
4. risks and unresolved decisions;
5. exact commands you will run.

Then implement Phase 0 only:
- FastAPI app entry point;
- settings via Pydantic Settings;
- SQLite SQLAlchemy engine/session with WAL, foreign keys, and busy timeout;
- health endpoint;
- minimal Jinja dashboard shell with a visible system status;
- Alembic initialized and first migration;
- pytest tests for health and DB connectivity;
- Ruff config and a working local run command.

Do not add paid services, API keys, cloud deployment, Redis, PostgreSQL, vector databases, browser automation, or external side effects. Do not generate fake candidate data. Keep the app bound to localhost. Update README with exact setup/run/test commands. Run tests and lint and report actual results.
