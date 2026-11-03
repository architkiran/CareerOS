from collections.abc import Iterator

from fastapi import Request
from pydantic import ValidationError
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def error_messages(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"] if p != "__root__")
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{loc.replace('_', ' ')}: {msg}" if loc else msg)
    return out
