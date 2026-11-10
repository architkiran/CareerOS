"""Small manually labeled regression set; measures this fixture, not the whole labor market."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from careeros.db.models import RoleLane
from careeros.modules.matching.inputs import ALGORITHM_VERSION, JobInput, MatchInput, ProfileInput
from careeros.modules.matching.scoring import evaluate
from careeros.modules.matching.service import build_lane_input
from careeros.modules.profile.defaults import DEFAULT_LANES


def evaluate_file(path: Path) -> dict[str, Any]:
    cases = json.loads(path.read_text())
    default = DEFAULT_LANES[0]
    base_lane = build_lane_input(
        RoleLane(
            name=default.name,
            rules_json=default.rules.model_dump(),
            scoring_weights_json=default.weights.model_dump(),
        )
    )
    # Synthetic candidate for a repeatable test. Never copied into the user's profile.
    profile = ProfileInput(
        verified_skills=("SQL", "Python", "Power BI", "Tableau"),
        evidence_text="sql python reporting dashboards",
        has_verified_evidence=True,
        current_location="Boston, MA",
        open_to_relocation=True,
        needs_sponsorship="yes",
    )
    results, false_positives, false_negatives, gate_errors, violations = [], [], [], [], []
    for case in cases:
        job = JobInput(
            title=case["title"],
            company="Evaluation fixture",
            location_text=case.get("location_text", "Boston, MA"),
            workplace_type=case.get("workplace_type"),
            employment_type=case.get("employment_type", "full_time"),
            description=case["description"],
            salary_min=None,
            salary_max=None,
            salary_interval=None,
            status=case.get("status", "active"),
        )
        lane = (
            replace(base_lane, title_keywords=tuple(case["keywords"]))
            if "keywords" in case
            else base_lane
        )
        result = evaluate(MatchInput(job, lane, profile))
        expected = case["relevant"] and case.get("gate") != "fail"
        actual = result.classified and result.eligibility != "fail"
        if actual and not expected:
            false_positives.append(case["id"])
        if expected and not actual:
            false_negatives.append(case["id"])
        if result.classified != case["relevant"] or (
            "gate" in case and result.eligibility != case["gate"]
        ):
            gate_errors.append(case["id"])
        if any(f.decision == "fail" for f in result.filters) and result.eligibility != "fail":
            violations.append(case["id"])
        results.append(
            {
                "id": case["id"],
                "relevant": result.classified,
                "eligibility": result.eligibility,
                "score": result.score,
                "expected_relevant": case["relevant"],
                "expected_gate": case.get("gate"),
                "concerns": [f.reason for f in result.filters if f.decision != "pass"],
            }
        )
    return {
        "algorithm": ALGORITHM_VERSION,
        "cases": len(cases),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "label_mismatches": gate_errors,
        "hard_gate_violations": violations,
        "results": results,
        "limitation": (
            "Small hand-labeled regression fixture, "
            "not an estimate of production precision or recall."
        ),
    }
