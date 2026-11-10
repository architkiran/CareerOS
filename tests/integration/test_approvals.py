import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from careeros.common.clock import utcnow
from careeros.db.models import Application, Approval, FollowUp, OutreachDraft
from careeros.modules.applications import service as apps
from careeros.modules.approvals import service as gate
from careeros.modules.documents import service as docs
from careeros.modules.outreach import service as outreach
from careeros.modules.profile import service as profile_service
from careeros.modules.profile.schemas import SkillIn
from tests.conftest import post_form
from tests.integration.test_documents import _setup


@pytest.fixture
def factory(app: FastAPI) -> sessionmaker[Session]:
    return app.state.session_factory  # type: ignore[no-any-return]


@pytest.fixture
def data_dir(app: FastAPI) -> Path:
    return Path(app.state.settings.data_dir)


def _ready_app(f: sessionmaker[Session], data_dir: Path, letter: bool = False) -> str:
    jid = _setup(f)
    with f() as s:
        app = apps.start_application(s, jid)
        for t in ("resume", "cover_letter") if letter else ("resume",):
            d = docs.generate(s, app.id, t, data_dir)  # type: ignore[arg-type]
            docs.acknowledge(s, d.id)
        s.commit()
        return app.id


def test_requires_ready_resume(factory: sessionmaker[Session], data_dir: Path) -> None:
    jid = _setup(factory)
    with factory() as s:
        app = apps.start_application(s, jid)
        with pytest.raises(gate.ApprovalError, match="resume"):
            gate.application_payload(s, app.id, False)
        docs.generate(s, app.id, "resume", data_dir)  # needs_ack, not ready
        with pytest.raises(gate.ApprovalError, match="resume"):
            gate.application_payload(s, app.id, False)


@pytest.mark.parametrize("artifact", ["binary", "json", "missing", "legacy"])
def test_changed_document_invalidates_exact_approval(
    factory: sessionmaker[Session], data_dir: Path, artifact: str
) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        payload = gate.application_payload(s, app_id, False)
        approval = gate.request(s, payload, data_dir)
        assert gate.snapshot(approval)["data"]["documents"][0]["file_hash"]
        gate.decide(s, approval.id, True, confirmed=True)
        doc = docs.latest(s, app_id, "resume")
        assert doc is not None
        path = Path(doc.storage_path)
        if artifact == "binary":
            path.write_bytes(b"changed after approval")
        elif artifact == "json":
            path.with_suffix(".json").write_text("{}")
        elif artifact == "missing":
            path.unlink()
        else:
            doc.file_hash = None
        with pytest.raises(gate.ApprovalError, match="invalidated"):
            gate.confirm_done(s, approval.id, confirmed=True)
        assert approval.status == "invalidated"
        assert s.get(Application, app_id).status != "submitted"  # type: ignore[union-attr]
        with pytest.raises(gate.ApprovalError):
            gate.application_payload(s, app_id, False)


def test_cover_letter_must_be_ready_if_included(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s, pytest.raises(gate.ApprovalError, match="cover letter"):
        gate.application_payload(s, app_id, True)


def test_full_happy_path(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir, letter=True)
    with factory() as s:
        payload = gate.application_payload(s, app_id, True)
        a = gate.request(s, payload, data_dir)
        s.commit()
        snap = gate.snapshot(a)
        assert [d["type"] for d in snap["data"]["documents"]] == ["resume", "cover_letter"]
        assert a.destination.startswith("https://") and a.status == "pending"
        assert oct(Path(a.payload_snapshot_path).stat().st_mode)[-3:] == "600"
        with pytest.raises(gate.ApprovalError, match="confirmation"):
            gate.decide(s, a.id, True, confirmed=False)
        gate.decide(s, a.id, True, confirmed=True)
        with pytest.raises(gate.ApprovalError, match="Confirm"):
            gate.confirm_done(s, a.id, confirmed=False)
        gate.confirm_done(s, a.id, confirmed=True)
        s.commit()
        app = s.get(Application, app_id)
        assert app is not None and app.status == "submitted" and app.submitted_at
        fu = s.scalars(select(FollowUp)).one()
        assert fu.due_at - app.submitted_at == timedelta(days=7)
        assert app.next_follow_up_at == fu.due_at
        assert a.status == "used" and a.used_at
        with pytest.raises(gate.ApprovalError, match="used"):  # single use
            gate.confirm_done(s, a.id, confirmed=True)


def test_no_submission_without_approval(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        with pytest.raises(gate.ApprovalError, match="pending, not approved"):
            gate.confirm_done(s, a.id, confirmed=True)
        assert s.get(Application, app_id).status != "submitted"  # type: ignore[union-attr]


def test_changed_document_invalidates_approval(
    factory: sessionmaker[Session], data_dir: Path
) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        gate.decide(s, a.id, True, confirmed=True)
        s.commit()
        profile_service.add_skill(s, SkillIn(name="Excel", verified_status="verified"))
        new = docs.generate(s, app_id, "resume", data_dir)
        docs.acknowledge(s, new.id)
        s.commit()
        with pytest.raises(gate.ApprovalError, match="invalidated"):
            gate.confirm_done(s, a.id, confirmed=True)
        assert a.status == "invalidated" and "changed" in (a.decision_note or "")
        assert s.get(Application, app_id).status != "submitted"  # type: ignore[union-attr]


def test_expired_approval_cannot_be_used(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        gate.decide(s, a.id, True, confirmed=True)
        a.expires_at = utcnow() - timedelta(minutes=1)
        with pytest.raises(gate.ApprovalError, match="expired"):
            gate.confirm_done(s, a.id, confirmed=True)


def test_new_request_supersedes_old(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        b = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        assert a.status == "invalidated" and b.status == "pending"
        with pytest.raises(gate.ApprovalError):
            gate.decide(s, a.id, True, confirmed=True)


def test_tampered_snapshot_detected(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        Path(a.payload_snapshot_path).write_text(json.dumps({"forged": True}))
        with pytest.raises(gate.ApprovalError, match="hash"):
            gate.snapshot(a)
        gate.refresh(s, a)
        assert a.status == "invalidated"


def test_rejection_and_future_time(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        a = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        gate.decide(s, a.id, False, confirmed=False, note="Not yet")
        assert a.status == "rejected" and a.decision_note == "Not yet"
        b = gate.request(s, gate.application_payload(s, app_id, False), data_dir)
        gate.decide(s, b.id, True, confirmed=True)
        with pytest.raises(gate.ApprovalError, match="future"):
            gate.confirm_done(s, b.id, confirmed=True, when=utcnow() + timedelta(days=1))


def test_outreach_draft_flow(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        app = s.get(Application, app_id)
        assert app is not None
        from careeros.db.models import Job

        job = s.get(Job, app.job_id)
        assert job is not None
        c = outreach.add_contact(s, job.company_id, outreach.ContactIn(name="Sam Recruiter"))
        d = outreach.save_draft(
            s,
            c.id,
            outreach.DraftIn(
                channel="email", recipient="sam@acme.example", subject="Hello", body="Hi Sam"
            ),
            data_dir,
            application_id=app_id,
        )
        a = gate.request(s, gate.outreach_payload(s, d.id), data_dir)
        gate.decide(s, a.id, True, confirmed=True)
        outreach.save_draft(
            s,
            c.id,
            outreach.DraftIn(
                channel="email",
                recipient="sam@acme.example",
                subject="Hello",
                body="Hi Sam, edited",
            ),
            data_dir,
            draft_id=d.id,
        )
        with pytest.raises(gate.ApprovalError, match="invalidated"):
            gate.confirm_done(s, a.id, confirmed=True)
        a2 = gate.request(s, gate.outreach_payload(s, d.id), data_dir)
        gate.decide(s, a2.id, True, confirmed=True)
        gate.confirm_done(s, a2.id, confirmed=True)
        assert d.status == "sent" and outreach.read_body(d) == "Hi Sam, edited"
        with pytest.raises(gate.ApprovalError, match="sent"):
            gate.outreach_payload(s, d.id)
        with pytest.raises(ValueError, match="already sent"):
            outreach.save_draft(
                s,
                c.id,
                outreach.DraftIn(channel="email", recipient="x", body="y"),
                data_dir,
                draft_id=d.id,
            )


def test_outreach_validation() -> None:
    with pytest.raises(ValueError, match="Channel"):
        outreach.DraftIn(channel="sms", recipient="x", body="y")
    with pytest.raises(ValueError, match="http"):
        outreach.ContactIn(name="x", public_profile_url="javascript:alert(1)")


def test_follow_ups(factory: sessionmaker[Session], data_dir: Path) -> None:
    app_id = _ready_app(factory, data_dir)
    with factory() as s:
        late = gate.add_follow_up(s, app_id, utcnow() - timedelta(days=1), "follow_up")
        later = gate.add_follow_up(s, app_id, utcnow() + timedelta(days=10), "check_status")
        app = s.get(Application, app_id)
        assert app is not None and app.next_follow_up_at == late.due_at
        rows = gate.open_follow_ups(s, due_within_days=3)
        assert [r.follow_up.id for r in rows] == [late.id] and rows[0].overdue
        gate.close_follow_up(s, late.id, "done")
        assert app.next_follow_up_at == later.due_at
        gate.close_follow_up(s, later.id, "skipped")
        assert app.next_follow_up_at is None
        with pytest.raises(gate.ApprovalError):
            gate.close_follow_up(s, late.id, "maybe")  # type: ignore[arg-type]
        with pytest.raises(LookupError):
            gate.add_follow_up(s, "missing", utcnow(), "x")


# ---------- web ----------


def test_web_submission_flow(
    factory: sessionmaker[Session], client: TestClient, data_dir: Path
) -> None:
    app_id = _ready_app(factory, data_dir)
    assert 'data-testid="approvals-empty"' in client.get("/approvals").text
    page = client.get(f"/applications/{app_id}").text
    assert 'data-testid="request-approval"' in page
    r = post_form(client, f"/applications/{app_id}/approval")
    url = r.headers["location"]
    html = client.get(url).text
    assert 'data-testid="approval-status">pending<' in html and 'data-testid="package"' in html
    assert "Download exactly this version" in html and 'rel="noopener noreferrer nofollow"' in html
    assert 'data-testid="stat-approvals">1<' in client.get("/partials/overview").text
    no_confirm = post_form(client, f"{url}/decide", {"decision": "approve"})
    assert "error=" in no_confirm.headers["location"]
    assert 'data-testid="approval-error"' in client.get(no_confirm.headers["location"]).text
    post_form(client, f"{url}/decide", {"decision": "approve", "confirmed": "on"})
    assert 'data-testid="confirm-done"' in client.get(url).text
    post_form(client, f"{url}/done", {"confirmed": "on", "when": "2026-11-02T14:30"})
    assert 'data-testid="approval-status">used<' in client.get(url).text
    assert 'data-testid="app-status">Applied<' in client.get(f"/applications/{app_id}").text
    assert client.get("/follow-ups").text.count('data-testid="follow-up-row"') == 1
    assert 'data-testid="audit"' in client.get("/approvals").text
    assert post_form(client, f"{url}/decide", {"decision": "maybe"}).status_code == 422
    assert post_form(client, "/approvals/missing/done", {"confirmed": "on"}).status_code == 404
    with factory() as s:
        app = s.get(Application, app_id)
        assert app is not None and app.submitted_at is not None
        assert app.submitted_at.hour == 19  # 14:30 Eastern stored as UTC


def test_web_request_blocked_without_ready_resume(
    factory: sessionmaker[Session], client: TestClient
) -> None:
    jid = _setup(factory)
    r = post_form(client, f"/jobs/{jid}/application")
    app_id = r.headers["location"].rsplit("/", 1)[1]
    assert 'data-testid="submit-blocked"' in client.get(f"/applications/{app_id}").text
    bad = post_form(client, f"/applications/{app_id}/approval")
    assert bad.status_code == 422 and "resume must pass QA" in bad.text


def test_web_outreach_and_follow_ups(
    factory: sessionmaker[Session], client: TestClient, data_dir: Path
) -> None:
    app_id = _ready_app(factory, data_dir)
    bad = post_form(
        client,
        f"/applications/{app_id}/outreach",
        {"name": "Sam", "channel": "carrier-pigeon", "recipient": "x", "body": "hi"},
    )
    assert bad.status_code == 422
    post_form(
        client,
        f"/applications/{app_id}/outreach",
        {"name": "Sam", "channel": "email", "recipient": "sam@acme.example", "body": "<b>Hi</b>"},
    )
    page = client.get(f"/applications/{app_id}").text
    assert 'data-testid="draft"' in page and "&lt;b&gt;Hi" in page
    with factory() as s:
        draft = s.scalars(select(OutreachDraft)).one()
    r = post_form(client, f"/outreach/{draft.id}/approval")
    assert (
        r.status_code == 303
        and 'data-testid="message-body"' in client.get(r.headers["location"]).text
    )
    post_form(
        client, f"/outreach/{draft.id}/edit", {"recipient": "sam@acme.example", "body": "Changed"}
    )
    with factory() as s:
        assert s.scalars(select(Approval)).one().status in ("pending", "invalidated")
    client.get("/approvals")
    with factory() as s:
        assert s.scalars(select(Approval)).one().status == "invalidated"
    assert (
        post_form(client, f"/applications/{app_id}/follow-ups", {"due": "nope"}).status_code == 422
    )
    post_form(
        client,
        f"/applications/{app_id}/follow-ups",
        {"due": "2026-12-01", "action_type": "thank_you"},
    )
    with factory() as s:
        fu = s.scalars(select(FollowUp)).one()
    r = post_form(
        client, f"/follow-ups/{fu.id}/close", {"status": "done", "back": "https://evil.example"}
    )
    assert r.headers["location"] == f"/applications/{app_id}#follow-ups"  # no open redirect
