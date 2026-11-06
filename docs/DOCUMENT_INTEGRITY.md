# Generated-document integrity

Migration 0014 adds a nullable SHA-256 `file_hash` to generated documents. New
versions record the exact Word binary after rendering alongside the existing JSON
content hash. Acknowledgment, download and application approval check both files.
Missing, malformed, changed or symbolic-link artifacts cannot pass the gate.

Approval snapshots bind document type, immutable version, content hash and binary
hash. Rechecking an approved package detects byte changes and invalidates approval
before completion can be recorded. Old snapshots without a binary binding cannot
authorize a new package. Historical approval records are retained.

The migration does not hash existing files: doing so would bless unknown content.
Legacy files remain on disk but must be regenerated as a new version before
download or approval through the app. Failed integrity checks are visible in the
application workspace. Regeneration preserves the old file and claim map, even if
its JSON content is identical; an intact unchanged version is reused.

This protects artifact consistency, not the truth of arbitrary locally edited
database records. Verified profile evidence and the human review gate remain
necessary. It also does not establish layout fidelity: the existing generic Word
renderer does not preserve a master PDF's exact format, and the workspace says so.
The original role-family PDFs remain separate, hash-checked references.

Tests cover JSON and binary tampering, missing files, legacy records, immutable
regeneration, approval invalidation, exact version links and migration consistency.
