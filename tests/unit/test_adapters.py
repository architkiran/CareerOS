from datetime import UTC, datetime

import pytest

from careeros.modules.sources.adapters import ADAPTERS, InvalidPayloadError
from careeros.modules.sources.adapters.base import (
    employment_from_text,
    parse_epoch_ms,
    parse_iso,
    require_list,
    validate_token,
    workplace_from_text,
)
from tests.helpers import load_fixture

GH = ADAPTERS["greenhouse"]
LV = ADAPTERS["lever"]
AB = ADAPTERS["ashby"]


def test_greenhouse_normalize() -> None:
    raw = load_fixture("greenhouse_jobs.json")["jobs"][0]
    job = GH.normalize(raw, "Fallback Co")
    assert job.external_id == "4012345"
    assert job.title == "Data Analyst"
    assert job.company_name == "ExamplePay"
    assert job.location_text == "New York, NY"
    assert job.department == "Analytics"
    assert job.employment_type == "full_time"  # from the board's "Time Type" field
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_interval) == (
        85000,
        110000,
        "USD",
        "year",
    )  # single range; the zone range is ignored
    assert job.posted_at == datetime(2026, 10, 20, 13, 0, tzinfo=UTC)
    assert "<" not in job.description_text and "alert(1)" not in job.description_text
    assert "- SQL" in job.description_text
    assert job.raw == raw


def test_greenhouse_remote_only_when_stated() -> None:
    jobs = load_fixture("greenhouse_jobs.json")["jobs"]
    assert GH.normalize(jobs[1], "X").workplace_type == "remote"
    assert GH.normalize(jobs[0], "X").workplace_type is None


def test_greenhouse_missing_company_uses_source_name() -> None:
    raw = load_fixture("greenhouse_jobs.json")["jobs"][2]
    assert GH.normalize(raw, "ExamplePay").company_name == "ExamplePay"


def test_greenhouse_malformed_item_rejected() -> None:
    raw = load_fixture("greenhouse_jobs.json")["jobs"][3]
    with pytest.raises(InvalidPayloadError):
        GH.normalize(raw, "X")


def test_lever_normalize_with_salary() -> None:
    raw = load_fixture("lever_postings.json")[0]
    job = LV.normalize(raw, "ExampleBank")
    assert job.title == "Business Operations Analyst"
    assert job.employment_type == "full_time"
    assert job.workplace_type == "hybrid"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (85000, 105000, "USD")
    assert "Requirements" in job.description_text and "- SQL" in job.description_text
    assert job.posted_at is not None and job.posted_at.tzinfo is not None


def test_lever_contract_and_no_salary() -> None:
    job = LV.normalize(load_fixture("lever_postings.json")[1], "ExampleBank")
    assert job.employment_type == "contract"
    assert job.workplace_type == "remote"
    assert job.salary_min is None and job.salary_max is None


def test_lever_missing_url_rejected() -> None:
    with pytest.raises(InvalidPayloadError):
        LV.normalize({"id": "x", "text": "T"}, "C")


def test_ashby_normalize_salary_only_from_salary_component() -> None:
    raw = load_fixture("ashby_jobs.json")["jobs"][0]
    job = AB.normalize(raw, "ExampleCard")
    assert job.employment_type == "full_time"
    assert job.workplace_type == "onsite"
    assert (job.salary_min, job.salary_max, job.salary_interval) == (110000, 140000, "year")


def test_ashby_intern_and_remote() -> None:
    job = AB.normalize(load_fixture("ashby_jobs.json")["jobs"][2], "ExampleCard")
    assert job.employment_type == "internship"
    assert job.workplace_type == "remote"
    assert job.description_text == "Internship."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Full-time", "full_time"),
        ("Employee: Full Time", "full_time"),
        ("FullTime", "full_time"),
        ("PartTime", "part_time"),
        ("Intern", "internship"),
        ("Co-op", "internship"),
        ("Contract", "contract"),
        ("Temporary", "temporary"),
        ("Mystery", None),
        (None, None),
    ],
)
def test_employment_mapping(text: str | None, expected: str | None) -> None:
    assert employment_from_text(text) == expected


def test_workplace_mapping() -> None:
    assert workplace_from_text("OnSite") == "onsite"
    assert workplace_from_text("unspecified") is None


@pytest.mark.parametrize("token", ["../etc", "a b", "", "x" * 101, "a/b"])
def test_invalid_tokens_rejected(token: str) -> None:
    with pytest.raises(ValueError):
        validate_token(token)


def test_list_urls_are_public_endpoints() -> None:
    assert GH.list_url("acme") == "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    assert LV.list_url("acme") == "https://api.lever.co/v0/postings/acme"
    assert AB.list_url("acme") == "https://api.ashbyhq.com/posting-api/job-board/acme"


def test_require_list_rejects_wrong_shape() -> None:
    with pytest.raises(InvalidPayloadError):
        require_list({"jobs": "nope"}, "jobs")
    with pytest.raises(InvalidPayloadError):
        require_list({"items": []}, "jobs")
    assert require_list([{"a": 1}, "junk"], None) == [{"a": 1}]


def test_date_parsing_edge_cases() -> None:
    assert parse_iso("not a date") is None
    assert parse_iso("2026-01-01T00:00:00") == datetime(2026, 1, 1, tzinfo=UTC)
    assert parse_epoch_ms("123") is None
    assert parse_epoch_ms(True) is None


def test_greenhouse_metadata_contract_hourly_and_unknowns() -> None:
    jobs = load_fixture("greenhouse_jobs.json")["jobs"]
    contract = GH.normalize(jobs[1], "X")
    assert contract.employment_type == "contract"
    assert (contract.salary_min, contract.salary_max, contract.salary_interval) == (45, 60, "hour")
    unknown = GH.normalize(jobs[2], "X")
    assert unknown.employment_type is None  # Worker Type is null: not assumed
    # Small amounts with no stated frequency are kept but never treated as yearly.
    assert (unknown.salary_min, unknown.salary_interval) == (15, "unspecified")


def test_greenhouse_metadata_garbage_is_ignored() -> None:
    raw = dict(load_fixture("greenhouse_jobs.json")["jobs"][0])
    raw["metadata"] = [
        {"name": "Pay Range", "value": {"min_value": "abc", "max_value": None}},
        "junk",
        {"name": "Time Type", "value": 42},
    ]
    job = GH.normalize(raw, "X")
    assert job.employment_type is None and job.salary_min is None


def test_greenhouse_update_time_is_not_publication_time() -> None:
    raw = load_fixture("greenhouse_jobs.json")["jobs"][1]
    assert raw.get("updated_at") and not raw.get("first_published")
    assert GH.normalize(raw, "ExamplePay").posted_at is None
