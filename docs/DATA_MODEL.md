# Data model

## Current default workflow — 10 November 2026

Migration `0016` adds source-time semantics and append-only `job_revision`;
`Job.published_at` is an ORM synonym for existing stored `posted_at`, not another
publication column. Job and source records keep publication kind, source
modification and retrieval time. Source records track authoritative presence.
Migration `0017` adds saved_stage/next_action and expiring sponsorship display
state/evidence. Matches and work authorization retain their existing verified
architecture. See the implementation report for the exact field map.

[Verified implementation and limits](SIMPLIFICATION_IMPLEMENTATION.md).


Use SQLAlchemy models and Alembic migrations. UUID/ULID string IDs are acceptable; choose one and use it consistently. Timestamps are UTC. Store raw source snapshots separately from generated documents.

## Core entities

### Candidate profile
- `candidate_profile`: id, display_name, email (optional), phone (optional), current_location, relocation_preferences_json, graduation_date, availability_date, salary_floor, created_at, updated_at.
- `profile_fact`: id, profile_id, category, fact_key, fact_value, verified_status, source_note, verified_at, created_at. Facts are individually traceable.
- `skill`: id, canonical_name, aliases_json.
- `candidate_skill`: profile_id, skill_id, proficiency, evidence_fact_ids_json, last_used_year, verified_status.
- `experience`: id, organization, title, start_date, end_date, description, verified_status.
- `project`: id, name, description, technologies_json, outcomes_json, evidence_notes, verified_status.
- `role_lane`: id, name, enabled, rules_json, scoring_weights_json, resume_template_id.
- `work_authorization_profile`: user-entered status, relevant dates, constraints, notes, verified_at. Sensitive; encrypt or minimize and never log.

### Sources and jobs
- `source`: id, source_type, display_name, base_url, enabled, rate_limit_seconds, config_json, last_success_at, last_error_at.
- `source_run`: id, source_id, started_at, finished_at, status, fetched_count, new_count, updated_count, error_summary.
- `job`: id, canonical_url, company_id, title, location_text, workplace_type, employment_type, seniority, description_text, description_hash, posted_at, first_seen_at, last_seen_at, expires_at, status, source_confidence.
- `job_source_record`: id, job_id, source_id, external_id, source_url, raw_snapshot_path or raw_json, first_seen_at, last_seen_at. Unique `(source_id, external_id)` where possible.
- `company`: id, canonical_name, domain, careers_url, company_notes.
- `job_lane_match`: id, job_id, role_lane_id, score, score_breakdown_json, hard_filter_results_json, explanation, created_at, algorithm_version.

Deduplicate with normalized canonical URL, source external ID, and normalized `(company, title, location)` plus description hash. Do not rely on title alone. Keep source records even when canonical jobs merge.

### Research and evidence
- `research_item`: id, company_id, job_id nullable, research_type, status, summary, confidence, reviewed_at.
- `evidence`: id, research_item_id, claim_type, claim_text, source_url, source_title, source_date, retrieved_at, confidence, short_excerpt, reviewer_status.
- Evidence must support sponsorship, work authorization, salary, location, and employer facts. Unknown is a valid state.

### Applications and documents
- `application`: id, job_id, status, priority, created_at, updated_at, submitted_at, next_follow_up_at, outcome, notes.
- `document`: id, application_id, document_type, version, storage_path, content_hash, generated_at, base_template_id, model_provider, model_name, status.
- `document_claim`: id, document_id, claim_text, supporting_profile_fact_ids_json, verification_status, warning.
- `application_answer`: id, application_id, question_key, question_text, answer_text, source_fact_ids_json, status.
- `application_event`: id, application_id, event_type, occurred_at, notes, source.

### Approvals and outreach
- `approval`: id, action_type, target_type, target_id, payload_hash, payload_snapshot_path, status, requested_at, expires_at, decided_at, decision_note, actor.
- `outreach_contact`: id, company_id, name, role, public_profile_url, source_url, notes.
- `outreach_draft`: id, contact_id, application_id nullable, channel, recipient, subject, body_path, payload_hash, status, created_at.
- `follow_up`: id, application_id, contact_id nullable, due_at, action_type, status, completed_at.

### Operations
- `task`: queue fields from ARCHITECTURE.md.
- `pipeline_run`: id, pipeline_name, status, started_at, finished_at, counters_json, error_summary.
- `activity_event`: id, event_type, entity_type, entity_id, message, metadata_json, created_at.
- `model_usage`: id, task_name, provider, model, input_tokens, output_tokens, estimated_cost, cache_hit, duration_ms, created_at.
- `setting`: key, value_json, updated_at.

## Required constraints and indexes

- unique source external ID per source;
- unique idempotency key for tasks where applicable;
- unique `(application_id, document_type, version)`;
- indexes on job first_seen_at, status, company_id, title;
- indexes on task status/run_after and event created_at/id;
- indexes on application status and next_follow_up_at;
- foreign keys enabled;
- soft-delete or archive important records rather than destructive deletion.

## Privacy and retention

Keep candidate personal data minimal. Store documents under a private data directory with restrictive permissions. Do not commit `data/`, `exports/`, raw resumes, generated documents, or `.env`. Provide export and delete controls. Do not store credentials in the database unless necessary; prefer OS keychain or environment variables. Consider field-level encryption before remote deployment.
