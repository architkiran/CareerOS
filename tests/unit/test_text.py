from careeros.modules.sources.text import (
    canonicalize_url,
    html_to_text,
    normalize_company,
    normalize_key,
)


def test_html_to_text_strips_tags_and_scripts() -> None:
    text = html_to_text("<p>Hello <b>world</b></p><script>alert(1)</script><style>p{}</style>")
    assert text == "Hello world"


def test_html_to_text_handles_double_escaped_html() -> None:
    assert html_to_text("&lt;p&gt;A &amp;amp; B&lt;/p&gt;") == "A & B"


def test_html_to_text_lists_and_blocks() -> None:
    assert html_to_text("<ul><li>SQL</li><li>Python</li></ul>") == "- SQL\n\n- Python"


def test_html_to_text_empty() -> None:
    assert html_to_text(None) == "" and html_to_text("") == ""


def test_plain_text_with_angle_brackets_survives() -> None:
    assert "5 > 3" in html_to_text("Requirement: 5 > 3 years")


def test_canonicalize_url_removes_tracking_and_fragment() -> None:
    url = "HTTPS://Boards.Greenhouse.io/acme/jobs/1/?gh_src=x&utm_source=li&b=2&a=1#apply"
    assert canonicalize_url(url) == "https://boards.greenhouse.io/acme/jobs/1?a=1&b=2"


def test_canonicalize_url_idempotent() -> None:
    once = canonicalize_url("https://jobs.lever.co/acme/123?lever-source=x")
    assert canonicalize_url(once) == once == "https://jobs.lever.co/acme/123"


def test_normalize_company_drops_suffixes() -> None:
    assert normalize_company("Acme, Inc.") == normalize_company("ACME") == "acme"


def test_normalize_key_collapses_punctuation() -> None:
    assert normalize_key("  Data  Analyst (NYC)! ") == "data analyst nyc"


def test_canonicalize_keeps_job_identifying_params() -> None:
    a = canonicalize_url("https://stripe.com/jobs/search?gh_jid=5416444")
    b = canonicalize_url("https://stripe.com/jobs/search?gh_jid=5601879&utm_source=x&gh_src=y")
    assert a == "https://stripe.com/jobs/search?gh_jid=5416444"
    assert b == "https://stripe.com/jobs/search?gh_jid=5601879"
    assert a != b


def test_canonicalize_keeps_generic_params() -> None:
    assert canonicalize_url("https://careers.example.com/job?id=7&ref=abc") == (
        "https://careers.example.com/job?id=7&ref=abc"
    )
