import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from careeros.modules.sources.adapters.community import CommunityFeedAdapter, clean_url
from careeros.modules.sources.adapters.workday import (
    WorkdayAdapter,
    parse_token,
    posted_days_ago,
)
from careeros.modules.sources.harvest import board_from_url, harvest, to_toml
from careeros.modules.sources.http import SourceBlockedError, SourceNotFoundError
from careeros.modules.sources.registry import SourceIn

HOST = "https://acme.wd5.myworkdayjobs.com"
INFO = {
    "title": "Data Analyst I",
    "jobDescription": "<p>Entry level. <b>SQL</b> required.</p>",
    "location": "Boston, MA",
    "additionalLocations": ["New York, NY"],
    "country": {"descriptor": "United States of America"},
    "timeType": "Full time",
    "startDate": "2026-11-09",
    "externalUrl": HOST + "/en-US/Careers/job/Boston/Data-Analyst-I_R1",
    "jobReqId": "R1",
}


class Workday:
    def __init__(self, robots="User-agent: *\nAllow: /\n", postings=None):
        self.robots, self.calls, self.posts = robots, [], []
        self.postings = postings or [
            {
                "title": "Data Analyst I",
                "externalPath": "/job/Boston/Data-Analyst-I_R1",
                "postedOn": "Posted Yesterday",
            },
            {
                "title": "Senior Data Analyst",
                "externalPath": "/job/Boston/Senior_R2",
                "postedOn": "Posted Today",
            },
            {
                "title": "Operations Analyst",
                "externalPath": "/job/NYC/Ops_R3",
                "postedOn": "Posted 30+ Days Ago",
            },
        ]

    def get_text(self, url, **kwargs):
        if self.robots is None:
            raise SourceNotFoundError("404", 404)
        return self.robots, 200

    def post_json(self, url, body, **kwargs):
        self.posts.append((url, body))
        return {"total": len(self.postings), "jobPostings": deepcopy(self.postings)}, 200

    def get_json(self, url, **kwargs):
        self.calls.append(url)
        return {"jobPostingInfo": deepcopy(INFO)}, 200


def test_workday_fetches_details_only_for_new_plausible_titles():
    feed, adapter = Workday(), WorkdayAdapter()
    rows, status = adapter.fetch_raw_incremental(feed, "acme.wd5.Careers", 1.0, {"/job/NYC/Ops_R3"})
    assert status == 200
    assert feed.posts[0][0] == HOST + "/wday/cxs/acme/Careers/jobs"
    assert feed.posts[0][1]["limit"] == 20
    assert feed.calls == [HOST + "/wday/cxs/acme/Careers/job/Boston/Data-Analyst-I_R1"]
    assert {"id": "/job/NYC/Ops_R3", "_seen_only": True} in rows
    job = adapter.normalize(next(r for r in rows if "detail" in r), "Acme")
    assert job.title == "Data Analyst I" and job.employment_type == "full_time"
    assert job.location_text == "Boston, MA; New York, NY (United States of America)"
    assert job.posted_at == datetime(2026, 11, 9, tzinfo=UTC)
    assert job.source_url.endswith("Data-Analyst-I_R1") and "SQL" in job.description_text
    assert job.company_name == "Acme"


def test_workday_honours_robots_disallow_and_missing_robots():
    blocked = Workday(robots="User-agent: *\nDisallow: /wday/\n")
    with pytest.raises(SourceBlockedError):
        WorkdayAdapter().fetch_raw(blocked, "acme.wd5.Careers", 1.0)
    assert blocked.posts == []
    rows, _ = WorkdayAdapter().fetch_raw(Workday(robots=None), "acme.wd5.Careers", 1.0)
    assert any("detail" in r for r in rows)


def test_workday_token_and_posted_text_parsing():
    assert parse_token("statestreet.wd1.Global") == ("statestreet", "wd1", "Global")
    for bad in ("statestreet", "a.b.c", "a.wd1."):
        with pytest.raises(ValueError):
            parse_token(bad)
    assert [posted_days_ago(t) for t in ("Posted Today", "Posted 3 Days Ago", None)] == [
        0,
        3,
        999,
    ]
    assert SourceIn(type="workday", token="acme.wd5.Careers", name="Acme").type == "workday"


def test_community_feed_keeps_only_active_recent_listings_and_never_invents_text():
    now = datetime.now(UTC).timestamp()
    listing = {
        "id": "abc",
        "title": "Data Analyst",
        "company_name": "Acme",
        "active": True,
        "is_visible": True,
        "date_posted": int(now) - 3600,
        "locations": ["Boston, MA", "NYC"],
        "url": "https://boards.greenhouse.io/acme/jobs/123?utm_source=Simplify&ref=Simplify",
        "sponsorship": "Offers Sponsorship",
    }
    old = dict(listing, id="old", date_posted=int(now) - 90 * 86400)
    closed = dict(listing, id="closed", active=False)

    class Feed:
        def get_json(self, url, **kwargs):
            assert url.startswith("https://raw.githubusercontent.com/SimplifyJobs/")
            return [listing, old, closed, "junk"], 200

    adapter = CommunityFeedAdapter()
    rows, _ = adapter.fetch_raw(Feed(), "simplify-newgrad", 2.0)
    assert [r["id"] for r in rows] == ["abc"]
    job = adapter.normalize(rows[0], "ignored")
    assert job.source_url == "https://boards.greenhouse.io/acme/jobs/123"
    assert job.description_text == "" and job.company_name == "Acme"
    assert job.location_text == "Boston, MA; NYC" and job.raw["sponsorship"] == "Offers Sponsorship"
    assert clean_url("https://x.com/j?id=7&utm_medium=a") == "https://x.com/j?id=7"


def test_harvest_reads_board_tokens_from_real_posting_urls_only():
    cases = {
        "https://job-boards.greenhouse.io/acme/jobs/123": ("greenhouse", "acme"),
        "https://boards.greenhouse.io/acme/jobs/9": ("greenhouse", "acme"),
        "https://jobs.lever.co/bank/0a1b2c3d-1111-2222-3333-444455556666": ("lever", "bank"),
        "https://jobs.ashbyhq.com/ramp/0a1b2c3d-1111-2222-3333-444455556666": ("ashby", "ramp"),
        "https://citi.wd5.myworkdayjobs.com/en-US/2/job/NY/Analyst_1": ("workday", "citi.wd5.2"),
        "https://mfs.wd1.myworkdayjobs.com/MFS-Careers/job/Boston/X_1": (
            "workday",
            "mfs.wd1.MFS-Careers",
        ),
        "https://example.com/careers/123": None,
        "https://boards.greenhouse.io/embed/jobs/1": None,
    }
    for url, expected in cases.items():
        assert board_from_url(url) == expected, url
    boards = harvest(
        [(u, "Acme") for u in cases] + [("https://jobs.lever.co/bank/" + "a" * 9, "B")]
    )
    assert (boards[0].type, boards[0].listings) in {("greenhouse", 2), ("lever", 2)}
    toml = to_toml(boards, "header")
    assert 'token = "citi.wd5.2"' in toml and json.dumps("x")  # valid TOML is checked below
    import tomllib

    assert len(tomllib.loads(toml)["source"]) == len(boards)
