# Cost and deployment plan

## Cost target

**Required monthly spend: $0.** The product must remain useful without paid model APIs, hosting, databases, email services, or scraping vendors.

## What is free in the MVP

- Development: existing Claude Pro/Claude Code subscription.
- Runtime: Python application on the user's Mac.
- Database: SQLite.
- Queue/scheduler: SQLite task table + APScheduler/OS scheduler.
- Dashboard: local FastAPI/Jinja/HTMX.
- Job discovery: public ATS endpoints and carefully selected official pages.
- Documents: local python-docx.
- AI at runtime: disabled by default; optional local model.
- Backups: local encrypted/controlled backup to a second location the user already owns.

Claude Pro is not an API credit balance. Claude Code is for development; do not assume the running application can call Claude at no additional cost.

## Local operation

- Start web server on `127.0.0.1`.
- Run worker locally.
- Schedule discovery at user-chosen times; start with once daily.
- Dashboard is available while the Mac is on.
- If laptop sleeps, scheduled work pauses. Show last-run timestamp and missed-run status instead of pretending the system is always online.

## Optional remote access

Only after local MVP works:
- use a reputable private mesh VPN for personal remote access, or
- deploy to a genuinely free compute tier if one is available and its limits/retention are understood.

Do not promise a free always-on VPS. Free tiers change and often sleep, throttle, or require a payment method. Never move sensitive candidate data to a cloud host without explicit consent and encryption/authentication.

## Optional local AI

Model gateway order:
1. deterministic code/rules;
2. cached prior results;
3. optional local Ollama model if installed and machine resources allow;
4. optional external API only after explicit cost approval.

Local inference has no API bill but consumes RAM, battery, and time. Use it for summarization/classification, not as a required dependency. Benchmark against deterministic baseline.

## Budget controls

- Global daily and monthly spend caps default to $0.
- API provider disabled unless explicitly configured.
- Require an explicit setting to permit paid calls.
- Estimate cost before a call; reject if it exceeds budget.
- Cache by normalized input hash + prompt version + model version.
- Log token counts, duration, cache hits, and estimated cost.
- Never call a model once per job by default. Batch only where safe and useful.
- Use small models/local inference for low-risk tasks; stronger models only for a small, user-approved set.

## Deployment evolution

Phase 1: local Mac, no Docker required.
Phase 2: optional Docker Compose for reproducibility.
Phase 3: optional remote worker/dashboard after security review and user approval.
Never add Kubernetes, managed Postgres, Redis, paid observability, or paid search APIs for a one-user MVP.
