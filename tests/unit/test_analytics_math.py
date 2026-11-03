import pytest

from careeros.modules.analytics.service import Rate, Segment, _reached, _recommend


def test_wilson_interval() -> None:
    lo, hi = Rate(5, 10).interval  # type: ignore[misc]
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert Rate(0, 10).interval[0] == 0.0  # type: ignore[index]
    assert Rate(10, 10).interval[1] == 1.0  # type: ignore[index]
    assert Rate(0, 0).value is None and Rate(0, 0).interval is None


def test_small_sample_flag() -> None:
    assert Rate(1, 9).small and not Rate(1, 10).small


def test_reached_is_cumulative() -> None:
    assert _reached({"preparing"}) == set()
    assert _reached({"submitted", "rejected"}) == {"submitted"}
    assert _reached({"interview", "rejected"}) == {"submitted", "response", "screen", "interview"}
    assert _reached({"offer"}) == {"submitted", "response", "screen", "interview", "offer"}


def seg(name: str, hits: int, n: int) -> Segment:
    return Segment(name, n, Rate(hits, n), Rate(hits, n))


def test_recommend_requires_enough_data() -> None:
    [msg] = _recommend("By lane", [seg("A", 3, 4), seg("B", 0, 3)])
    assert "not enough data" in msg and "7 submitted" in msg
    assert _recommend("By lane", []) == []


def test_recommend_requires_non_overlapping_intervals() -> None:
    [msg] = _recommend("By lane", [seg("A", 4, 10), seg("B", 3, 10)])
    assert "no clear difference" in msg


def test_recommend_clear_difference() -> None:
    [msg] = _recommend("By lane", [seg("A", 18, 20), seg("B", 2, 20)])
    assert "'A' converts to interviews more often than 'B'" in msg and "18/20 vs 2/20" in msg
