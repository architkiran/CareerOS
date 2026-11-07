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
        ("Data Analyst", "Requires 5+ years of experience in SQL.", "senior", "high"),
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


def test_required_experience_is_not_lowered_by_bonus_experience():
    desc = (
        "Requirements\n- 4+ years in Product Operations or Program Management.\n"
        "Bonus points\n- 1+ years managing a team."
    )
    result = infer_seniority("Product Operations Manager", desc)
    assert (result.min_years, result.level, result.confidence) == (4, "mid", "high")


def test_explicit_minimum_experience_in_saved_posting():
    result = infer_seniority(
        "Commercial Data Scientist",
        "At least 4 years of professional experience as a Data Scientist or other related roles.",
    )
    assert result.min_years == 4 and result.confidence == "high"


def test_preferred_experience_does_not_become_a_hard_requirement():
    result = infer_seniority(
        "Data Analyst", "Preferred qualifications\n5+ years of experience with SQL."
    )
    assert result.confidence == "medium"


def test_alternative_degree_requirements_remain_for_review():
    result = infer_seniority(
        "Analyst",
        (
            "Requirements: 4 years of experience with a Bachelor degree "
            "or 2 years of experience with a Master degree."
        ),
    )
    assert result.confidence == "medium" and result.min_years == 2


def test_decimal_experience_is_not_misread_as_five_years():
    result = infer_seniority("Analyst", "Minimum 1.5 years of experience.")
    assert result.level is None


def test_entry_title_and_higher_required_experience_are_conflicting():
    result = infer_seniority("Junior Data Analyst", "Minimum 5 years of experience.")
    assert result.confidence == "medium" and "conflicts" in result.rationale
