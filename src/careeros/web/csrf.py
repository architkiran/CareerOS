"""Double-submit CSRF protection for state-changing browser requests.

A random token lives in a SameSite=Strict, HttpOnly cookie and is echoed in a
hidden form field (or X-CSRF-Token header). Unsafe requests must match.
"""

import hmac
import secrets
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response

COOKIE_NAME = "careeros_csrf"
FIELD_NAME = "csrf_token"
HEADER_NAME = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def csrf_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    existing = request.cookies.get(COOKIE_NAME)
    token = existing or secrets.token_urlsafe(32)
    request.state.csrf_token = token
    response = await call_next(request)
    if not existing:
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict", path="/")
    return response


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency. Rejects unsafe requests without a matching token."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(COOKIE_NAME, "")
    sent = request.headers.get(HEADER_NAME)
    if sent is None:
        form = await request.form()
        value = form.get(FIELD_NAME)
        sent = value if isinstance(value, str) else ""
    if not cookie or not sent or not hmac.compare_digest(cookie, sent):
        raise HTTPException(
            status_code=403, detail="CSRF token missing or invalid. Reload the page."
        )
