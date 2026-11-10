"""Run the repository's labeled, offline matching check."""

import json
from pathlib import Path

from careeros.modules.matching.evaluation import evaluate_file

if __name__ == "__main__":
    report = evaluate_file(
        Path(__file__).resolve().parents[1] / "tests/fixtures/matching/labeled_jobs.json"
    )
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["label_mismatches"] or report["hard_gate_violations"]))
