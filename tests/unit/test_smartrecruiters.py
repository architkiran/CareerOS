from copy import deepcopy

import pytest

from careeros.modules.sources.adapters.base import InvalidPayloadError
from careeros.modules.sources.adapters.smartrecruiters import SmartRecruitersAdapter

DETAIL = {
    "id": "123",
    "name": "Data Analyst",
    "applyUrl": "https://jobs.smartrecruiters.com/Wise/123",
    "active": True,
    "location": {"city": "Austin", "country": "us", "remote": False},
    "releasedDate": "2026-11-06T00:00:00Z",
    "typeOfEmployment": {"label": "Full-time"},
    "jobAd": {"sections": {"jobDescription": {"text": "<p>SQL and Python</p>"}}},
}


class Feed:
    def __init__(self, total=1, ref="http://127.0.0.1/private"):
        self.calls = []
        self.total = total
        self.ref = ref

    def get_json(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/postings"):
            return {"totalFound": self.total, "content": [{"id": "123", "ref": self.ref}]}, 200
        return deepcopy(DETAIL), 200


def test_public_detail_url_is_built_locally_and_fields_are_explicit():
    feed = Feed()
    adapter = SmartRecruitersAdapter()
    rows, status = adapter.fetch_raw(feed, "wise", 2)
    assert status == 200 and all(
        url.startswith("https://api.smartrecruiters.com/") for url in feed.calls
    )
    job = adapter.normalize(rows[0], "Wise")
    assert job.employment_type == "full_time" and job.workplace_type is None
    assert job.salary_min is None and job.description_text == "SQL and Python"
    assert job.posted_at and job.posted_at.year == 2026


def test_excessive_board_fails_before_detail_requests():
    feed = Feed(total=201)
    with pytest.raises(InvalidPayloadError, match="bounded"):
        SmartRecruitersAdapter().fetch_raw(feed, "wise", 2)
    assert len(feed.calls) == 1


def test_missing_description_and_unsafe_tokens_rejected():
    adapter = SmartRecruitersAdapter()
    data = deepcopy(DETAIL)
    data["jobAd"] = {}
    with pytest.raises(InvalidPayloadError, match="description"):
        adapter.normalize(data, "Wise")
    with pytest.raises(ValueError):
        adapter.list_url("../private")
