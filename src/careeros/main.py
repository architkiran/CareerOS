"""Application factory and command-line entry point."""

import argparse
import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from careeros import __version__
from careeros.common.logging import configure_logging
from careeros.config import Settings, get_settings
from careeros.db.session import create_sqlite_engine, make_session_factory
from careeros.web.csrf import csrf_middleware
from careeros.web.routes import profile, system
from careeros.web.templating import STATIC_DIR, build_templates

logger = logging.getLogger("careeros")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    settings.ensure_private_dirs()

    app = FastAPI(title="CareerOS", version=__version__, docs_url=None, redoc_url=None)
    engine = create_sqlite_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.templates = build_templates(settings.display_timezone)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.middleware("http")(csrf_middleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(system.router)
    app.include_router(profile.router)

    if not settings.is_localhost_bound:
        logger.warning("Bound to %s, not localhost. Add authentication first.", settings.app_host)
    return app


def _serve(settings: Settings) -> None:
    import uvicorn

    uvicorn.run(create_app(settings), host=settings.app_host, port=settings.app_port)


def _migrate(settings: Settings) -> None:
    from careeros.db.migrations import upgrade_to_head

    configure_logging(settings.log_level)
    settings.ensure_private_dirs()
    upgrade_to_head(settings.database_url)
    print("Database is at the latest migration.")


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="careeros", description="CareerOS local server")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="Run the dashboard (default)")
    sub.add_parser("migrate", help="Apply database migrations")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "migrate":
        _migrate(settings)
    else:
        _serve(settings)


if __name__ == "__main__":
    run()
