"""Everything the Overview page shows, gathered in one place."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.config import Settings
from careeros.db.models import PipelineRun, Source, Task
from careeros.modules.jobs.service import JobCounts, job_counts
from careeros.modules.scheduler import queue
from careeros.modules.scheduler.worker import last_discovery, schedule_overdue


@dataclass
class SourceHealth:
    total: int
    enabled: int
    failing: int


@dataclass
class Overview:
    jobs: JobCounts
    sources: SourceHealth
    queue: queue.QueueStats
    dead_tasks: list[Task]
    last_run: PipelineRun | None
    last_success: PipelineRun | None
    running: bool
    scheduler_enabled: bool
    schedule_interval_hours: float
    schedule_overdue: bool
    worker_enabled: bool


def build_overview(session: Session, settings: Settings) -> Overview:
    total = int(session.scalar(select(func.count()).select_from(Source)) or 0)
    enabled = int(
        session.scalar(select(func.count()).select_from(Source).where(Source.enabled)) or 0
    )
    failing = int(
        session.scalar(
            select(func.count()).select_from(Source).where(Source.last_error.is_not(None))
        )
        or 0
    )
    stats = queue.queue_stats(session)
    return Overview(
        jobs=job_counts(session, settings.display_timezone),
        sources=SourceHealth(total, enabled, failing),
        queue=stats,
        dead_tasks=queue.dead_tasks(session, 5),
        last_run=last_discovery(session),
        last_success=last_discovery(session, successful=True),
        running=stats.running > 0,
        scheduler_enabled=settings.scheduler_enabled,
        schedule_interval_hours=settings.schedule_interval_hours,
        schedule_overdue=settings.scheduler_enabled
        and schedule_overdue(session, settings.schedule_interval_hours),
        worker_enabled=settings.worker_enabled,
    )
