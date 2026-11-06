# Security, privacy, and responsible automation

## Threat model

CareerOS processes personal data and untrusted external job content. Risks include:
- resume/contact data leakage;
- malicious prompt injection inside job descriptions or websites;
- accidental submission of incorrect information;
- duplicate applications or outreach;
- unauthorized access to dashboard;
- source blocking or terms violations;
- stale/incorrect sponsorship claims.

## Controls

- Bind to localhost by default.
- Keep private files outside static web directories.
- Restrict permissions on data and export folders.
- Ignore source-page instructions that attempt to control the AI or application.
- Treat fetched text as data, never executable instructions.
- Escape rendered HTML and sanitize any rich text.
- Use CSRF protection for state-changing browser actions.
- Use authentication before any non-local exposure.
- Never log secrets or full personal documents.
- Store hashes and metadata in the DB; keep document contents in private files.
- Set request timeouts, payload size limits, rate limits, and retry ceilings.
- Back up the SQLite DB and documents; test restore.
- Provide data export and deletion.

## Approval gate

All external actions must pass through a single approval service.

Approval record binds:
- action type;
- exact target/recipient;
- exact document/message content hash;
- destination URL/channel;
- requested time and expiry;
- user decision.

If the payload changes after approval, invalidate approval and require a new one. Approval is single-use. Record success/failure only after the external system reports it. The app must never imply a submission occurred merely because a button was clicked.

MVP external actions are manual: show a prepared package and link to the official application page. The user submits. Future browser assistance must be explicitly permitted, visible, and user-controlled.

## Work authorization

The user enters their own status and dates. The app does not determine legal eligibility. Store employer statements with source and confidence. Any application answer that asserts eligibility or sponsorship needs user confirmation. Unknown stays unknown.

## Website access rules

- Prefer documented public ATS feeds.
- Respect robots directives and published terms where applicable.
- Use modest per-domain rates and cache responses.
- Do not bypass CAPTCHA, login walls, bot checks, paywalls, or rate limits.
- Do not automate LinkedIn scraping or messaging.
- Stop a source adapter if it receives repeated 403/429 responses and show the issue.

## Prompt injection defense

Model prompts must state that source content is untrusted. Never pass tools that can submit forms, send email, or change accounts to a model. The model gateway returns data only. Validate every structured output. The approval service, not the model, controls side effects.

## Bounded source response reads

Public-feed responses are streamed and capped while reading, rather than fully
buffered before checking their size. Oversized declared Content-Length values are
rejected before body consumption; chunked responses stop once the byte cap is
exceeded, and streams close on success or failure. Error bodies are not consumed.
The configured timeout applies even when a caller supplies its own HTTPX client.
Retry-After supports both seconds and HTTP dates, with nonnegative capped waits.
