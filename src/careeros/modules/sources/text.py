"""Text normalization helpers. Source HTML is untrusted: we only extract text."""

import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "section",
}
_SKIP_TAGS = {"script", "style", "noscript", "template"}
# Only parameters known to be pure tracking. Anything else may identify the job:
# company-hosted Greenhouse pages, for example, differ only by `gh_jid`.
_TRACKING_PARAMS = {"gh_src", "lever-source", "lever-origin"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str:
    """Convert (possibly entity-escaped) HTML into plain text. Never returns markup."""
    if not value:
        return ""
    # Greenhouse double-encodes: unescape once so tags become real tags.
    raw = html.unescape(value) if "&lt;" in value else value
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = "".join(parser.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str | None) -> str:
    """Lowercase, strip punctuation and collapse whitespace for matching."""
    lowered = normalize_space(value).lower()
    lowered = re.sub(r"[^\w\s/&+-]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_company(value: str) -> str:
    key = normalize_key(value)
    key = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company)\b\.?", "", key)
    return re.sub(r"\s+", " ", key).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(sorted(query)), "")
    )


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
