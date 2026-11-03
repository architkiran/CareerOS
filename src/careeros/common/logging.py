"""Logging setup.

Never log secrets, full resumes, full application answers, or other sensitive
personal data. Log identifiers and counts instead.
"""

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(h, "_careeros", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._careeros = True  # type: ignore[attr-defined]
        root.addHandler(handler)
