from typing import Any

from sqlalchemy.orm import Session

from careeros.common.clock import utcnow
from careeros.db.models import Setting


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    return default if row is None else row.value_json


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value_json=value, updated_at=utcnow()))
    else:
        row.value_json = value
        row.updated_at = utcnow()
