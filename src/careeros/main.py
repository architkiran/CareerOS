"""Application factory and command-line entry point."""

import argparse
import asyncio
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
    companies,
    events,
    inbox,
    intake,
    interviews,
    jobs,
    market,
    profile,
    referrals,
    research,
    resumes,
    sources,
    system,
    today,
    watch,
    workbench,
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
        from careeros.modules.models import local_runtime

        local_model = await asyncio.to_thread(local_runtime.start, settings)
        worker = None
        from careeros.modules.system.status import get_system_status

        if (
            settings.worker_enabled
            and get_system_status(settings, app.state.engine).schema.up_to_date
        ):
            from careeros.modules.system.settings_store import get_setting, set_setting

            with app.state.session_factory() as session:
                from sqlalchemy import select

                from careeros.db.models import RoleLane
                from careeros.modules.profile.service import add_default_lanes

                if session.scalar(select(RoleLane.id).limit(1)) is None:
                    add_default_lanes(session)
                    session.commit()
                if get_setting(session, "watch.enabled") is None:
                    set_setting(session, "watch.enabled", settings.discovery_monitor_enabled)
                    session.commit()
            from careeros.modules.scheduler.worker import Worker

            worker = Worker(
                app.state.session_factory,
                scheduler_enabled=settings.scheduler_enabled,
                mission_scheduler_enabled=settings.mission_scheduler_enabled,
                schedule_interval_hours=settings.schedule_interval_hours,
                poll_seconds=settings.worker_poll_seconds,
                data_dir=settings.data_dir,
            )
            worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            await asyncio.to_thread(local_runtime.stop, local_model)

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
    app.include_router(today.router)
    app.include_router(inbox.router)
    app.include_router(intake.router)
    app.include_router(workbench.router)
    app.include_router(watch.router)
    app.include_router(system.router)
    app.include_router(agents.router)
    app.include_router(profile.router)
    app.include_router(resumes.router)
    app.include_router(market.router)
    app.include_router(interviews.router)
    app.include_router(companies.router)
    app.include_router(sources.router)
    app.include_router(jobs.router)
    app.include_router(events.router)
    app.include_router(research.router)
    app.include_router(referrals.router)
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
        data_dir=settings.data_dir,
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


def _discover(settings: Settings, args: argparse.Namespace) -> int:
    """Fetch enabled sources, evaluate every job against the hard rules, write the digest."""
    from careeros.common.clock import utcnow
    from careeros.modules.eligibility import service as eligibility
    from careeros.modules.ingestion.service import run_all
    from careeros.modules.sources import registry
    from careeros.modules.sources.http import Fetcher

    if not _require_current_schema(settings):
        return 1
    factory = _session_factory(settings)
    watchlist = Path(args.file)
    if watchlist.exists():
        with factory() as session:
            added = registry.sync_watchlist(session, registry.load_watchlist(watchlist)).added
            session.commit()
        if added:
            print(f"Added {added} new sources from {watchlist}.")
    if not args.no_fetch:
        fetcher = Fetcher()
        try:
            ids = None
            if args.types:
                from sqlalchemy import select

                from careeros.db.models import Source

                wanted = [t.strip() for t in args.types.split(",") if t.strip()]
                with factory() as session:
                    ids = list(
                        session.scalars(select(Source.id).where(Source.source_type.in_(wanted)))
                    )
            results = run_all(factory, fetcher, source_ids=ids)
        finally:
            fetcher.close()
        failed = [r for r in results if r.status == "failed"]
        new = sum(r.new for r in results)
        print(f"Sources run: {len(results)}; failed: {len(failed)}; new postings: {new}")
        for r in failed[:15]:
            print(f"  FAILED {r.source_name}: {r.error}")
    with factory() as session:
        summary = eligibility.evaluate_all(session)
        session.commit()
        digest = eligibility.build_digest(session)
        text = eligibility.digest_markdown(digest)
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    out = settings.export_dir / f"digest-{utcnow():%Y-%m-%d}.md"
    out.write_text(text)
    print(
        f"Evaluated {summary.evaluated} jobs: "
        + ", ".join(f"{k} {v}" for k, v in sorted(summary.by_verdict.items()))
    )
    print(f"Digest: {out}  |  Open http://127.0.0.1:{settings.app_port}/today")
    return 0


def _lca(settings: Settings, args: argparse.Namespace) -> int:
    from careeros.modules.sponsorship import lca

    if not _require_current_schema(settings):
        return 1
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    with _session_factory(settings)() as session:
        try:
            count = lca.import_file(session, path, args.fiscal_year)
        except lca.LcaImportError as exc:
            print(f"Import failed: {exc}", file=sys.stderr)
            return 1
        session.commit()
    print(f"Stored certified-LCA history for {count} employers (FY{args.fiscal_year}).")
    print("Run `careeros discover --no-fetch` to re-evaluate jobs with this evidence.")
    return 0


def _harvest(settings: Settings, args: argparse.Namespace) -> int:
    """Write a watchlist of official ATS boards read out of real posting URLs."""
    from datetime import date

    from sqlalchemy import select

    from careeros.db.models import Company, Job
    from careeros.modules.eligibility.engine import classify_role
    from careeros.modules.sources import harvest
    from careeros.modules.sources.adapters.community import FEEDS
    from careeros.modules.sources.http import Fetcher

    pairs: list[tuple[str, str]] = []
    relevant: list[tuple[str, str]] = []
    fetcher = Fetcher()
    try:
        for url in FEEDS.values():
            payload, _ = fetcher.get_json(url)
            for i in payload:
                if not isinstance(i, dict) or not i.get("active"):
                    continue
                pair = (str(i.get("url", "")), str(i.get("company_name", "")))
                title = str(i.get("title", ""))
                # Employers already posting roles in the target families come first.
                (
                    relevant if classify_role(title)[0] or "analyst" in title.lower() else pairs
                ).append(pair)
    finally:
        fetcher.close()
    if _require_current_schema(settings):
        with _session_factory(settings)() as session:
            pairs += [
                (url, name)
                for url, name in session.execute(
                    select(Job.canonical_url, Company.canonical_name).join(
                        Company, Company.id == Job.company_id
                    )
                )
            ]
    boards = harvest.harvest(relevant)
    known = {(b.type, b.token) for b in boards}
    boards += [b for b in harvest.harvest(pairs) if (b.type, b.token) not in known]
    boards = boards[: args.max]
    header = (
        f"Official ATS boards read from live employer posting URLs on {date.today()}.\n"
        "Generated by `careeros sources harvest`; tokens are never guessed.\n"
        "A board that later returns 404 is disabled automatically."
    )
    Path(args.write).write_text(harvest.to_toml(boards, header))
    kinds: dict[str, int] = {}
    for b in boards:
        kinds[b.type] = kinds.get(b.type, 0) + 1
    print(f"Wrote {len(boards)} boards to {args.write}: {kinds}")
    print(f"Next: careeros discover --file {args.write}")
    return 0


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
    hv = src_sub.add_parser("harvest", help="Build a watchlist from real posting URLs")
    hv.add_argument("--write", default="config/sources.discovered.toml")
    hv.add_argument("--max", type=int, default=250)
    disc = sub.add_parser("discover", help="Fetch, evaluate eligibility and write the digest")
    disc.add_argument("--file", default="config/sources.toml")
    disc.add_argument("--no-fetch", action="store_true", help="Only re-evaluate stored jobs")
    disc.add_argument("--types", help="Only these source types, e.g. community,greenhouse")
    lca_p = sub.add_parser("lca", help="Import US DOL LCA disclosure data")
    lca_sub = lca_p.add_subparsers(dest="lca_command", required=True)
    lca_imp = lca_sub.add_parser("import", help="Aggregate an LCA disclosure .xlsx or .csv")
    lca_imp.add_argument("file")
    lca_imp.add_argument("--fiscal-year", type=int, required=True)
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
    elif args.command == "sources" and args.sources_command == "harvest":
        raise SystemExit(_harvest(settings, args))
    elif args.command == "sources":
        raise SystemExit(_sources(settings, args))
    elif args.command == "discover":
        raise SystemExit(_discover(settings, args))
    elif args.command == "lca":
        raise SystemExit(_lca(settings, args))
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
