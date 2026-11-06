import pytest

from careeros.modules.sources.adapters.base import InvalidPayloadError
from careeros.modules.sources.adapters.wwr import WWRAdapter


def test_wwr_rss_retains_employer_original_link_and_publication_time():
    adapter = WWRAdapter()
    job = adapter.normalize(
        {
            "title": "Acme: Data Analyst",
            "guid": "x",
            "link": "https://weworkremotely.com/remote-jobs/acme-data-analyst",
            "pubDate": "Fri, 06 Nov 2026 12:00:00 +0000",
            "description": "<p>SQL reporting</p>",
            "region": "USA",
        },
        "WWR",
    )
    assert job.company_name == "Acme" and job.title == "Data Analyst"
    assert job.posted_at.hour == 12 and job.description_text == "SQL reporting"
    with pytest.raises(InvalidPayloadError):
        adapter.normalize({"title": "Acme: Analyst", "link": "https://other.example/job"}, "WWR")


def test_wwr_rejects_xml_entities():
    class Feed:
        def get_text(self, *args, **kwargs):
            return (
                '<!DOCTYPE rss [<!ENTITY x "secret">]><rss><channel>'
                "<item><title>&x;</title></item></channel></rss>",
                200,
            )

    with pytest.raises(InvalidPayloadError, match="unsafe"):
        WWRAdapter().fetch_raw(Feed(), "all", 2)
