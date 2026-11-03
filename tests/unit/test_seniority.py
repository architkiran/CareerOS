import pytest

from careeros.modules.matching.seniority import infer_seniority


@pytest.mark.parametrize(
    ("title", "desc", "level", "confidence"),
    [
        ("Senior Data Analyst", "", "senior", "high"),
        ("Sr. Business Analyst", "", "senior", "high"),
        ("Staff Data Engineer", "", "lead", "high"),
        ("Director of Analytics", "", "lead", "high"),
        ("Junior Data Analyst", "", "entry", "high"),
        ("Data Analyst, New Grad", "", "entry", "high"),
        ("Data Analyst II", "", "mid", "medium"),
        ("Analytics Manager", "", "lead", "medium"),
        ("Associate Consultant", "", "junior", "medium"),
        ("Data Analyst", "Requires 5+ years of experience in SQL.", "senior", "medium"),
        ("Data Analyst", "1-2 years of relevant experience preferred", "entry", "medium"),
        ("Data Analyst", "3+ years of professional experience", "mid", "medium"),
        ("Data Analyst", "Great team, great benefits.", None, None),
    ],
)
def test_infer(title: str, desc: str, level: str | None, confidence: str | None) -> None:
    g = infer_seniority(title, desc)
    assert (g.level, g.confidence) == (level, confidence)
    assert g.rationale


def test_title_high_confidence_beats_description() -> None:
    assert infer_seniority("Senior Analyst", "0-1 years of experience").level == "senior"


def test_description_beats_medium_title_signal() -> None:
    assert infer_seniority("Data Analyst II", "8+ years of experience").level == "lead"


def test_years_without_experience_word_ignored() -> None:
    assert infer_seniority("Data Analyst", "We are 10 years old as a company.").level is None


def test_min_years_reported() -> None:
    g = infer_seniority("Analyst", "2+ years of experience; 5 years of experience preferred")
    assert g.min_years == 2 and g.level == "junior"
