"""Application factory and command-line entry point."""

import argparse
import logging
import sys
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from careeros import __version__
from careeros.common.logging import configure_logging
from careeros.config import Settings, get_settings
from careeros.db.session import create_sqlite_engine, make_session_factory
from careeros.web import errors
from careeros.web.csrf import csrf_middleware
from careeros.web.routes import (
    agents,
    analytics,
    applications,
    approvals,
    events,
    jobs,
    profile,
    research,
    sources,
    system,
)
from careeros.web.routes import (
    settings as settings_routes,
)
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        worker = None
        if settings.worker_enabled:
            from careeros.modules.scheduler.worker import Worker

            worker = Worker(
                app.state.session_factory,
                scheduler_enabled=settings.scheduler_enabled,
                mission_scheduler_enabled=settings.mission_scheduler_enabled,
                schedule_interval_hours=settings.schedule_interval_hours,
                poll_seconds=settings.worker_poll_seconds,
            )
            worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()

    app = FastAPI(
        title="CareerOS", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan
    )
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

    errors.install(app)
    app.middleware("http")(csrf_middleware)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(system.router)
    app.include_router(agents.router)
    app.include_router(profile.router)
    app.include_router(sources.router)
    app.include_router(jobs.router)
    app.include_router(events.router)
    app.include_router(research.router)
    app.include_router(applications.router)
    app.include_router(approvals.router)
    app.include_router(analytics.router)
    app.include_router(settings_routes.router)

    if not settings.is_localhost_bound:
        logger.warning("Bound to %s, not localhost. Add authentication first.", settings.app_host)
    return app


def _serve(settings: Settings, *, with_worker: bool = True) -> None:
    import uvicorn

    if not settings.is_localhost_bound and not settings.allow_remote:
        print(
            f"Refusing to listen on {settings.app_host}: CareerOS has no login yet, so anyone on "
            "the network could see your data. Use 127.0.0.1, or set ALLOW_REMOTE=true only behind "
            "a private VPN you trust (see docs/REMOTE_ACCESS.md).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not with_worker:
        settings = settings.model_copy(update={"worker_enabled": False})
    uvicorn.run(
        create_app(settings),
        host=settings.app_host,
        port=settings.app_port,
        timeout_graceful_shutdown=3,  # don't hang on open SSE streams
    )


def _worker(settings: Settings) -> int:
    import signal

    from careeros.modules.scheduler.worker import Worker

    if not _require_current_schema(settings):
        return 1
    worker = Worker(
        _session_factory(settings),
        scheduler_enabled=settings.scheduler_enabled,
        mission_scheduler_enabled=settings.mission_scheduler_enabled,
        schedule_interval_hours=settings.schedule_interval_hours,
        poll_seconds=settings.worker_poll_seconds,
    )
    worker.start()
    print("Worker running. Press Ctrl+C to stop.")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
    return 0


def _migrate(settings: Settings) -> None:
    from careeros.db.migrations import upgrade_to_head

    configure_logging(settings.log_level)
    settings.ensure_private_dirs()
    upgrade_to_head(settings.database_url)
    print("Database is at the latest migration.")


def _require_current_schema(settings: Settings) -> bool:
    from careeros.db.migrations import current_revision, head_revision
    from careeros.db.session import create_sqlite_engine

    engine = create_sqlite_engine(settings.database_url)
    try:
        ok = current_revision(engine) == head_revision(settings.database_url)
    finally:
        engine.dispose()
    if not ok:
        print("Database migrations are pending. Run: careeros migrate", file=sys.stderr)
    return ok


def _session_factory(settings: Settings):  # type: ignore[no-untyped-def]
    from careeros.db.session import create_sqlite_engine

    return make_session_factory(create_sqlite_engine(settings.database_url))


def _sources(settings: Settings, args: argparse.Namespace) -> int:
    from careeros.modules.sources import registry

    if not _require_current_schema(settings):
        return 1
    factory = _session_factory(settings)
    with factory() as session:
        if args.sources_command == "sync":
            path = Path(args.file)
            if not path.exists():
                print(
                    f"Watchlist not found: {path}. Copy config/sources.example.toml first.",
                    file=sys.stderr,
                )
                return 1
            try:
                entries = registry.load_watchlist(path)
            except (ValueError, tomllib.TOMLDecodeError) as exc:
                print(f"Invalid watchlist: {exc}", file=sys.stderr)
                return 1
            result = registry.sync_watchlist(session, entries)
            session.commit()
            print(
                f"Sources: {result.added} added, {result.existing} already configured"
                + (f", {result.disabled} disabled." if result.disabled else ".")
            )
        else:
            for src in registry.list_sources(session):
                state = "enabled" if src.enabled else "disabled"
                print(f"{src.source_type:<11} {src.board_token:<24} {state:<9} {src.display_name}")
    return 0


def _ingest(settings: Settings, args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from careeros.db.models import Source
    from careeros.modules.ingestion.service import run_all
    from careeros.modules.sources.http import Fetcher

    if not _require_current_schema(settings):
        return 1
    factory = _session_factory(settings)
    ids = None
    if args.token:
        with factory() as session:
            ids = list(session.scalars(select(Source.id).where(Source.board_token == args.token)))
        if not ids:
            print(f"No source with token {args.token!r}.", file=sys.stderr)
            return 1
    fetcher = Fetcher()
    try:
        results = run_all(factory, fetcher, source_ids=ids)
    finally:
        fetcher.close()
    if not results:
        print("No enabled sources. Run: careeros sources sync")
        return 0
    for r in results:
        if r.status == "failed":
            print(f"FAILED  {r.source_name}: {r.error}")
        else:
            print(
                f"{r.status.upper():<7} {r.source_name}: {r.fetched} fetched, {r.new} new, "
                f"{r.updated} updated, {r.duplicates} duplicate, {r.invalid} invalid, "
                f"{r.closed} closed"
            )
    return 1 if all(r.status == "failed" for r in results) else 0


def _backup(settings: Settings, args: argparse.Namespace) -> int:
    from careeros.modules.backup import service as backup

    try:
        if args.verify:
            manifest = backup.verify_backup(Path(args.verify))
            files = manifest.get("files", {})
            print(f"OK: {len(files) if isinstance(files, dict) else 0} files verified.")
            return 0
        result = backup.create_backup(
            settings.database_url,
            settings.data_dir,
            Path(args.dest) if args.dest else settings.backup_dir,
        )
    except backup.BackupError as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup written and verified: {result.path} ({result.files} files)")
    print("Copy it somewhere you own (an external drive or your own cloud folder).")
    return 0


def _restore(settings: Settings, args: argparse.Namespace) -> int:
    from careeros.modules.backup import service as backup

    if not args.yes:
        print(
            "Restoring replaces your current database and documents. The current ones are "
            "moved aside, not deleted. Stop `careeros serve` first, then re-run with --yes.",
            file=sys.stderr,
        )
        return 1
    try:
        moved = backup.restore_backup(Path(args.archive), settings.database_url, settings.data_dir)
    except backup.BackupError as exc:
        print(f"Restore refused: {exc}", file=sys.stderr)
        return 1
    print("Restore complete." + (f" Previous database kept at {moved}" if moved else ""))
    print("Run `careeros migrate` in case the backup is from an older version.")
    return 0


def run(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="careeros", description="CareerOS local server")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the dashboard and worker (default)")
    serve.add_argument("--no-worker", action="store_true", help="Don't run tasks in this process")
    sub.add_parser("worker", help="Run only the task worker")
    sub.add_parser("migrate", help="Apply database migrations")
    src = sub.add_parser("sources", help="Manage the source watchlist")
    src_sub = src.add_subparsers(dest="sources_command", required=True)
    sync = src_sub.add_parser("sync", help="Add sources from a TOML watchlist")
    sync.add_argument("--file", default="config/sources.toml")
    src_sub.add_parser("list", help="List configured sources")
    bk = sub.add_parser("backup", help="Create a verified backup (or --verify one)")
    bk.add_argument("--dest", help="Folder for the archive (default BACKUP_DIR)")
    bk.add_argument("--verify", metavar="ARCHIVE", help="Only verify an existing backup")
    rs = sub.add_parser("restore", help="Restore a verified backup")
    rs.add_argument("archive")
    rs.add_argument("--yes", action="store_true", help="Confirm replacing current data")
    ingest = sub.add_parser("ingest", help="Fetch jobs from enabled sources now")
    ingest.add_argument("--token", help="Only this board token")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    if args.command == "migrate":
        _migrate(settings)
    elif args.command == "sources":
        raise SystemExit(_sources(settings, args))
    elif args.command == "ingest":
        raise SystemExit(_ingest(settings, args))
    elif args.command == "backup":
        raise SystemExit(_backup(settings, args))
    elif args.command == "restore":
        raise SystemExit(_restore(settings, args))
    elif args.command == "worker":
        raise SystemExit(_worker(settings))
    else:
        _serve(settings, with_worker=not getattr(args, "no_worker", False))


if __name__ == "__main__":
    run()
