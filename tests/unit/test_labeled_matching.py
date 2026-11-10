from pathlib import Path

from careeros.modules.matching.evaluation import evaluate_file
from careeros.modules.profile.schemas import LaneRules


def test_labeled_entry_level_fixture_has_no_gate_or_relevance_errors() -> None:
    report = evaluate_file(Path(__file__).parents[1] / "fixtures/matching/labeled_jobs.json")
    assert report["cases"] == 22
    assert report["false_positives"] == [] and report["false_negatives"] == []
    assert report["label_mismatches"] == [] and report["hard_gate_violations"] == []
    assert any(r["eligibility"] == "fail" and r["score"] >= 70 for r in report["results"])


def test_new_lane_defaults_do_not_silently_include_midcareer_roles() -> None:
    assert LaneRules().seniority_allowed == ["entry", "junior"]
    assert LaneRules(seniority_allowed=["mid"]).seniority_allowed == ["mid"]
