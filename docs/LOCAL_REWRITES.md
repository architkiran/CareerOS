# Local resume rewrites

The older template path selects evidence. It does not perform an AI rewrite.
The workbench now offers a separate, explicit **Rewrite with local AI** action.
A durable tailoring task proposes a new summary, role wording, projects and skills.
Verified tools explicitly named in the JD outrank the model's skill suggestions;
analyst roles also prioritize verified core BI skills. The proposal is capped at
18 skills to prevent the model flooding an analyst resume with unrelated tooling.
A focused second pass repairs unsafe role proposals; if validation still fails,
that role keeps its original bullets and the result shows a warning.

## Installed configuration on Archit's Mac

The pinned native llama.cpp server bundled with the official Ollama v0.40.15
release runs Qwen3 4B locally. It binds only to `127.0.0.1:11435`, requires a
private bearer key, and is started/stopped by CareerOS when CareerOS owns the
process. An already-running authenticated service is reused without taking
ownership. No cloud provider is implemented or enabled. Spend caps remain $0.

All runtime/model/key/log files are inside the repository's ignored `.tools/`.
The native Ollama daemon was not used because it creates files in the user's
home directory; this runtime needs no home-directory writes.

## Reproduce the installation

From this repository, run `.venv/bin/python scripts/setup_local_model.py`.
This explicit setup downloads approximately 2.7 GB of free public artifacts and
verifies pinned SHA-256 hashes. Startup itself never downloads a model.
Then set these values in `.env`:

```dotenv
MODEL_PROVIDER=llama_cpp
MODEL_TIMEOUT_SECONDS=180
LLAMA_BASE_URL=http://127.0.0.1:11435
LLAMA_MODEL=qwen3-4b.gguf
LLAMA_KEY_FILE=.tools/local-model.key
```

Launch `zsh "Start CareerOS.command"`. It can take several seconds to load the
model. For an existing Ollama installation, the original `ollama` provider is
still supported. On other platforms use Ollama and a locally installed model.
The default configuration for a new checkout remains `MODEL_PROVIDER=disabled`.

## Review boundary and limits

1. Open an application's tailoring workbench and supply editing instructions.
2. Queue a rewrite; its mission records progress, errors, retries and results.
3. Refresh the result. Compare every experience with its master evidence.
4. Use the proposed edits in the editor, adjust them, then save a PDF revision.
5. Inspect the rendered PDF and QA findings before approving any application.

A proposal never overwrites the master or a saved PDF. All experience references
must be retained. Source bullet counts, numeric tokens and known technology
mentions are checked; newly introduced domain, metric, ownership and tool claims
are rejected. Projects and skills must reference verified items. Profile/posting
changes invalidate the proposal. The model cache includes instructions and output
schema so editing preferences cannot accidentally reuse a different rewrite.

These checks are conservative heuristics, not semantic proof. A local 4B model
can still produce poor wording or an unsupported implication. Human review is
required. Role proposals that fail checks keep their originals visibly; a failed
summary blocks the proposal. Sparse source evidence stays sparse: the InternPe
record has no verified dates and only one substantive sentence. The system must
not invent a longer internship description.

Model usage metadata contains no prompt text. Proposal/request files are private
(mode 600 in directories mode 700). Current proposal replacement is atomic. No
submission, connection request or outreach is sent by this workflow.

## Discovery correction

Today leads with matches whose source reports publication in the last 24 hours.
Listings newly observed within seven days appear separately, including older initial
imports. Older high-scoring recommendations are secondary. Publication and discovery
times remain separate. Initial imports are not newly posted jobs. Additional explicit
non-US locations (including Serbia) now fail the US location filter; matching v5
invalidates older cached scores. Mixed US/international listings retain US eligibility.
Feeds poll within their provider limits while the local app/worker is running;
this is not continuous LinkedIn/Handshake monitoring or guaranteed minute-level
coverage. See **Monitoring & freshness** for per-source checks and cadence.

## Primary references

- [Tsenta tailoring workflow](https://help.tsenta.com/resume-tailoring-and-cover-letters): role-specific rewrites, review and edits inspired the review flow.
- [Ollama v0.40.15 release](https://github.com/ollama/ollama/releases/tag/v0.40.15): native runtime distribution.
- [Qwen3 4B](https://ollama.com/library/qwen3:4b): local model artifact.
- [Greenhouse public Job Board API](https://developers.greenhouse.io/job-board.html): permitted public employer feed integration.
