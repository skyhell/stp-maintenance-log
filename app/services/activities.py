"""Helpers for the self-building activity ("Tätigkeit") list."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity


def list_activities(db: Session) -> list[Activity]:
    """All activities, most recently used first."""
    return list(
        db.scalars(select(Activity).order_by(Activity.last_used_at.desc())).all()
    )


def get_or_create_activity(db: Session, name: str | None) -> Activity | None:
    """Return an existing activity (bumping its usage) or create a new one.

    The dropdown builds itself: any name typed in is stored the first time and
    ``last_used_at`` is updated on every use so recent ones sort first.
    """
    if not name:
        return None
    name = name.strip()
    if not name:
        return None

    activity = db.scalar(select(Activity).where(Activity.name == name))
    now = datetime.now(UTC)
    if activity:
        activity.last_used_at = now
        activity.use_count = (activity.use_count or 0) + 1
    else:
        activity = Activity(name=name, last_used_at=now, use_count=1)
        db.add(activity)
    db.flush()
    return activity
