from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Application, ApplicationEvent, Approval, Document, Task
from careeros.modules.applications import service as applications
from tests.conftest import post_form
from tests.integration.test_fresh_referrals import make_role


def test_manual_application_is_confirmed_dated_and_idempotent(
    session: Session, client: TestClient
) -> None:
    role = make_role(session)
    session.commit()
    when = (utcnow() - timedelta(days=3)).date().isoformat()
    data = {"confirmed": "on", "application_date": when, "notes": "Applied directly"}
    response = post_form(client, f"/jobs/{role.id}/record-applied", data)
    assert response.status_code == 303
    assert post_form(client, f"/jobs/{role.id}/record-applied", data).status_code == 303
    session.expire_all()
    app = session.scalar(select(Application))
    assert app.status == "submitted" and app.submitted_at.date().isoformat() == when
    assert app.notes == "Applied directly"
    events = list(
        session.scalars(
            select(ApplicationEvent).where(ApplicationEvent.event_type == "status:submitted")
        )
    )
    assert len(events) == 1 and events[0].source == "user_manual"
    for model in (Task, Document, Approval):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    applications.set_status(session, app.id, "interview")
    session.commit()
    assert post_form(client, f"/jobs/{role.id}/record-applied", data).status_code == 303
    session.expire_all()
    assert session.get(Application, app.id).status == "interview"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"confirmed": "on", "application_date": "bad"},
        {"confirmed": "on", "application_date": "2099-01-01"},
        {"confirmed": "on", "notes": "x" * 3001},
    ],
)
def test_invalid_manual_record_never_creates_application(
    session: Session, client: TestClient, data: dict
) -> None:
    role = make_role(session)
    session.commit()
    assert post_form(client, f"/jobs/{role.id}/record-applied", data).status_code == 422
    assert session.scalar(select(func.count()).select_from(Application)) == 0


def test_manual_tracking_csrf_and_missing_role(client: TestClient) -> None:
    assert client.post("/jobs/missing/record-applied", data={"confirmed": "on"}).status_code == 403
    assert post_form(client, "/jobs/missing/record-applied", {"confirmed": "on"}).status_code == 404
