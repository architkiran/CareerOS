import re
from datetime import UTC, datetime
from typing import Any, Protocol

from careeros.modules.sources.http import Fetcher
from careeros.modules.sources.schemas import EmploymentType, NormalizedJob, WorkplaceType

TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class InvalidPayloadError(ValueError):
    """The source response did not have the documented shape."""


class Adapter(Protocol):
    source_type: str

    def list_url(self, token: str) -> str: ...

    def fetch_raw(
        self, fetcher: Fetcher, token: str, min_interval: float
    ) -> tuple[list[dict[str, Any]], int]:
        """Return raw job dicts and the last HTTP status."""
        ...

    def normalize(self, raw: dict[str, Any], company_name: str) -> NormalizedJob: ...


def validate_token(token: str) -> str:
    if not TOKEN_RE.match(token):
        raise ValueError("Board token may only contain letters, digits, dot, dash and underscore.")
    return token


def parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_epoch_ms(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def employment_from_text(value: Any) -> EmploymentType | None:
    """Map an explicit source commitment string. Unrecognised means unknown (None)."""
    if not isinstance(value, str):
        return None
    v = value.lower().replace("-", " ").replace("_", " ")
    if "intern" in v or "co op" in v:
        return "internship"
    if "contract" in v or "freelance" in v or "contractor" in v:
        return "contract"
    if "temp" in v or "seasonal" in v:
        return "temporary"
    if "part time" in v or v.replace(" ", "") == "parttime":
        return "part_time"
    if "full time" in v or v.replace(" ", "") == "fulltime" or "permanent" in v:
        return "full_time"
    return None


def workplace_from_text(value: Any) -> WorkplaceType | None:
    if not isinstance(value, str):
        return None
    v = value.lower().replace("-", "").replace(" ", "")
    if v == "remote":
        return "remote"
    if v == "hybrid":
        return "hybrid"
    if v in {"onsite", "inoffice", "office"}:
        return "onsite"
    return None


def str_or_none(value: Any, limit: int = 500) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]
    return None


def require_list(payload: Any, key: str | None) -> list[dict[str, Any]]:
    items = payload.get(key) if key and isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise InvalidPayloadError(f"Expected a list{f' under {key!r}' if key else ''}")
    return [i for i in items if isinstance(i, dict)]
