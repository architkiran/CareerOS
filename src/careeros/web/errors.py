"""Readable HTML error pages for browser requests; JSON stays for machine endpoints."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

JSON_PATHS = ("/health", "/events/")
TITLES = {
    400: "That request didn't make sense",
    403: "This form expired",
    404: "Not found",
    405: "That action isn't available here",
    409: "Something doesn't match",
    422: "Some of that input wasn't valid",
    500: "Something went wrong",
}
HINTS = {
    403: "Reload the page and try again. Forms are protected so other sites can't submit them.",
    404: "It may have been removed, or the link is out of date.",
}


def wants_html(request: Request) -> bool:
    if request.url.path.startswith(JSON_PATHS):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept or (request.method == "POST" and "application/json" not in accept)


def _render(request: Request, status: int, detail: str | None) -> HTMLResponse:
    ctx: dict[str, Any] = {
        "code": status,
        "title": TITLES.get(status, "Something went wrong"),
        "detail": detail if detail and detail != "Not Found" else None,
        "hint": HINTS.get(status),
        "back": request.headers.get("referer") if _same_origin(request) else None,
    }
    response: HTMLResponse = request.app.state.templates.TemplateResponse(
        request, "error.html", ctx, status_code=status
    )
    return response


def _same_origin(request: Request) -> bool:
    ref = request.headers.get("referer", "")
    return ref.startswith(str(request.base_url))


def _validation_text(exc: RequestValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        field = ".".join(str(p) for p in err.get("loc", ()) if p not in ("query", "body", "path"))
        parts.append(f"{field}: {err.get('msg', 'invalid')}" if field else str(err.get("msg")))
    return "; ".join(parts)


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if wants_html(request):
            return _render(request, exc.status_code, str(exc.detail) if exc.detail else None)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        if wants_html(request):
            return _render(request, 422, _validation_text(exc))
        return await request_validation_exception_handler(request, exc)
