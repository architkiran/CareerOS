import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from careeros.config import Settings


def make(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_safe_defaults() -> None:
    s = make()
    assert s.app_host == "127.0.0.1"
    assert s.is_localhost_bound
    assert s.model_provider == "disabled"
    assert s.model_daily_budget_usd == 0
    assert s.model_monthly_budget_usd == 0
    assert s.scheduler_enabled is False


def test_rejects_non_sqlite_database() -> None:
    with pytest.raises(ValidationError, match="SQLite"):
        make(database_url="postgresql://localhost/careeros")


def test_rejects_negative_budget() -> None:
    with pytest.raises(ValidationError):
        make(model_daily_budget_usd=-1)


def test_rejects_unknown_model_provider() -> None:
    with pytest.raises(ValidationError):
        make(model_provider="openai")


def test_rejects_invalid_log_level() -> None:
    with pytest.raises(ValidationError):
        make(log_level="LOUD")


def test_log_level_normalized() -> None:
    assert make(log_level="debug").log_level == "DEBUG"


def test_non_localhost_host_is_flagged() -> None:
    assert not make(app_host="0.0.0.0").is_localhost_bound  # noqa: S104


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PORT", "9001")
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    s = make()
    assert s.app_port == 9001
    assert s.scheduler_enabled is True


def test_private_dirs_created_with_owner_only_permissions(tmp_path: Path) -> None:
    s = make(data_dir=tmp_path / "d", export_dir=tmp_path / "e")
    s.ensure_private_dirs()
    for path in (s.data_dir, s.export_dir):
        assert path.is_dir()
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_private_dirs_tolerate_foreign_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def deny(self: Path, mode: int) -> None:
        raise PermissionError("not owner")

    s = make(data_dir=tmp_path / "d", export_dir=tmp_path / "e")
    monkeypatch.setattr(Path, "chmod", deny)
    s.ensure_private_dirs()  # writable, so only a warning
    assert "Couldn't restrict permissions" in caplog.text


def test_private_dirs_fail_when_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny(self: Path, mode: int) -> None:
        raise PermissionError("not owner")

    s = make(data_dir=tmp_path / "d", export_dir=tmp_path / "e")
    monkeypatch.setattr(Path, "chmod", deny)
    monkeypatch.setattr("careeros.common.fs.os.access", lambda *_a: False)
    with pytest.raises(PermissionError):
        s.ensure_private_dirs()


def test_container_mode_counts_as_local_only_for_wildcard() -> None:
    assert make(container=True, app_host="0.0.0.0").is_localhost_bound  # noqa: S104
    assert not make(container=False, app_host="0.0.0.0").is_localhost_bound  # noqa: S104
    assert not make(container=True, app_host="192.168.1.5").is_localhost_bound


@pytest.mark.parametrize("hours", [0.25, 0.5, 1, 3, 6, 12, 24])
def test_supported_discovery_cadences(hours: float) -> None:
    assert make(schedule_interval_hours=hours).schedule_interval_hours == hours


def test_refuses_excessively_frequent_schedule() -> None:
    with pytest.raises(ValidationError):
        make(schedule_interval_hours=0.1)
