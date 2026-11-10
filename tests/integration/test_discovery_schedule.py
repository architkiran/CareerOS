from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Mission, SourceRun
from careeros.modules.sources.monitoring import coverage, refresh, set_interval, tick
from careeros.modules.sources.registry import SourceIn, add_source
from careeros.modules.system.settings_store import set_setting


def test_default_30_minutes_and_stricter_provider_cadence(session: Session) -> None:
    now = utcnow()
    ats = add_source(session, SourceIn(type="greenhouse", token="example", name="ATS"))
    board = add_source(session, SourceIn(type="remotive", token="public", name="Board"))
    for source in (ats, board):
        session.add(
            SourceRun(source_id=source.id, started_at=now, finished_at=now, status="success")
        )
    session.flush()
    rows = {r.id: r for r in coverage(session, now)}
    assert rows[ats.id].minutes == 30 and rows[board.id].minutes == 360
    assert rows[ats.id].next_due == now + timedelta(minutes=30)
    set_interval(session, 60)
    assert {r.id: r for r in coverage(session, now)}[ats.id].minutes == 60


def test_monitor_pause_and_duplicate_refresh(session: Session) -> None:
    add_source(session, SourceIn(type="greenhouse", token="example", name="Example"))
    set_setting(session, "watch.enabled", False)
    tick(session)
    assert session.scalar(select(func.count()).select_from(Mission)) == 0
    first, status = refresh(session)
    assert first and status == "queued"
    _, second_status = refresh(session)
    assert second_status == "already"
    assert session.scalar(select(func.count()).select_from(Mission)) == 1


def test_manual_refresh_respects_provider_minimum(session: Session) -> None:
    source = add_source(session, SourceIn(type="jobicy", token="usa", name="Board"))
    now = utcnow()
    session.add(
        SourceRun(
            source_id=source.id,
            started_at=now - timedelta(minutes=10),
            finished_at=now,
            status="success",
        )
    )
    session.flush()
    assert refresh(session) == (None, "cooldown")


def test_orphaned_refresh_is_interrupted_not_permanently_checking(session: Session) -> None:
    source = add_source(session, SourceIn(type="greenhouse", token="example", name="ATS"))
    now = utcnow()
    session.add(SourceRun(source_id=source.id, started_at=now - timedelta(hours=1)))
    session.flush()
    assert coverage(session, now)[0].state == "Interrupted"
    assert refresh(session)[1] == "queued"
