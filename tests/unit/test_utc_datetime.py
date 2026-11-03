from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import sqlite

from careeros.common.clock import utcnow
from careeros.db.base import UTCDateTime

DIALECT = sqlite.dialect()


def test_utcnow_is_aware_utc() -> None:
    assert utcnow().tzinfo is UTC


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValueError, match="Naive"):
        UTCDateTime().process_bind_param(datetime(2026, 1, 1), DIALECT)  # noqa: DTZ001


def test_aware_datetime_converted_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    stored = UTCDateTime().process_bind_param(datetime(2026, 1, 1, 9, tzinfo=eastern), DIALECT)
    assert stored == datetime(2026, 1, 1, 14)  # noqa: DTZ001


def test_none_passthrough() -> None:
    assert UTCDateTime().process_bind_param(None, DIALECT) is None
    assert UTCDateTime().process_result_value(None, DIALECT) is None


def test_result_is_aware_utc() -> None:
    value = UTCDateTime().process_result_value(datetime(2026, 1, 1, 14), DIALECT)  # noqa: DTZ001
    assert value == datetime(2026, 1, 1, 14, tzinfo=UTC)
