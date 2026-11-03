"""Private-folder helper shared by every module that writes personal data."""

import logging
import os
from pathlib import Path

logger = logging.getLogger("careeros")


def private_dir(path: Path) -> Path:
    """Create `path` and restrict it to the current user where the OS allows it.

    A folder mounted into a container may belong to another user; that's accepted
    as long as it is writable, with a warning.
    """
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except PermissionError:
        if not os.access(path, os.W_OK | os.X_OK):
            raise
        logger.warning(
            "Couldn't restrict permissions on %s (owned by another user); "
            "make sure only you can read it.",
            path,
        )
    return path
