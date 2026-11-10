from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import ActivityEvent
from careeros.modules.analytics.quality import compute_quality
from careeros.modules.applications.service import record_manual_application, set_status
from tests.integration.test_fresh_referrals import make_role, match


def test_delay_uses_only_trustworthy_original_publications(
    session: Session, client: TestClient
) -> None:
    now = utcnow()
    original = make_role(
        session,
        "Original",
        posted_at=now - timedelta(minutes=35),
        first_seen_at=now - timedelta(minutes=5),
    )
    original.publication_kind = "original"
    republish = make_role(session, "Republished", posted_at=now - timedelta(days=2))
    republish.publication_kind = "last_publication"
    invalid = make_role(session, "Unknown", posted_at=None)
    invalid.canonical_url = "javascript:alert(1)"
    negative = make_role(session, "Negative", posted_at=now, first_seen_at=now - timedelta(days=1))
    negative.publication_kind = "original"
    session.commit()
    data = compute_quality(session)
    assert data["publication_delay_n"] == 1 and data["publication_delay_minutes"] == 30
    assert data["valid_urls"] == 3 and data["url_availability"] is None
    assert "not HTTP availability checks" in client.get("/quality").text


def test_user_reviews_count_latest_per_role_and_score_snapshot_is_immutable(
    session: Session,
) -> None:
    role = make_role(session)
    match(session, role, score=85)
    app = record_manual_application(session, role.id, confirmed=True)
    set_status(session, app.id, "interview")
    for value in ("unsure", "fits"):
        session.add(
            ActivityEvent(
                event_type="job.eligibility_review",
                entity_id=role.id,
                message="User review",
                metadata_json={"decision": value},
            )
        )
    session.flush()
    data = compute_quality(session)
    assert data["eligibility_review"].n == 1 and data["eligibility_review"].hits == 1
    assert data["by_match_band"][0][0] == "80–100"
    assert data["by_match_band"][0][1].hits == 1
