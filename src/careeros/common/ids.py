"""Stable identifiers.

Entity tables use UUID4 strings. Append-only stream tables (activity_event)
use integer autoincrement IDs so they can serve as an ordered SSE cursor.
"""

import uuid


def new_id() -> str:
    return uuid.uuid4().hex
