"""Cursor-based pagination for SQLAlchemy queries."""

from __future__ import annotations

import base64
from typing import Any, Sequence, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def encode_cursor(last_id: int) -> str:
    """Encode an integer ID as a base64 cursor string."""
    return base64.urlsafe_b64encode(str(last_id).encode()).decode()


def decode_cursor(cursor: str) -> int:
    """Decode a base64 cursor string back to an integer ID."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return int(raw)
    except (ValueError, Exception) as exc:
        raise ValueError(f"Invalid cursor: {cursor!r}") from exc


def paginate_query(
    stmt: Select[Any],
    session: Session,
    *,
    id_column: Any,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[Sequence[Any], str | None]:
    """Apply cursor-based pagination to a SQLAlchemy select statement.

    Args:
        stmt: Base SELECT statement (ordering will be applied by this function).
        session: Active SQLAlchemy session.
        id_column: The mapped column to use for cursor (e.g. Alert.id).
        cursor: Opaque cursor from previous page (None for first page).
        limit: Maximum items to return.

    Returns:
        (items, next_cursor) — next_cursor is None when no more pages.
    """
    if limit < 1:
        limit = 1
    if limit > 1000:
        limit = 1000

    if cursor is not None:
        last_id = decode_cursor(cursor)
        stmt = stmt.where(id_column > last_id)

    stmt = stmt.order_by(id_column.asc()).limit(limit + 1)
    rows = list(session.execute(stmt).scalars().all())

    if len(rows) > limit:
        items = rows[:limit]
        last_item = items[-1]
        next_cursor = encode_cursor(last_item.id)
    else:
        items = rows
        next_cursor = None

    return items, next_cursor
