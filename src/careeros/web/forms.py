"""Helpers to turn HTML form fields into schema input."""

from starlette.datastructures import FormData


def text(form: FormData, key: str) -> str | None:
    value = form.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def csv_list(form: FormData, key: str) -> list[str]:
    raw = text(form, key) or ""
    return [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]


def lines(form: FormData, key: str) -> list[str]:
    raw = text(form, key) or ""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def checkbox(form: FormData, key: str) -> bool:
    return form.get(key) in {"on", "true", "1", "yes"}


def tri_state(form: FormData, key: str) -> bool | None:
    value = text(form, key)
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def multi(form: FormData, key: str) -> list[str]:
    return [v for v in form.getlist(key) if isinstance(v, str) and v]


def bounded_int(value: str | None, low: int, high: int) -> int | None:
    """Parse an optional integer query/form value; blank, junk or out-of-range means None."""
    if value is None or not value.strip():
        return None
    try:
        n = int(value.strip())
    except ValueError:
        return None
    return n if low <= n <= high else None
