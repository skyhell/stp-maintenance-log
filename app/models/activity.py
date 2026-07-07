"""Activity model: the self-building "Tätigkeit" dropdown.

New activities are stored automatically the first time they are used, and
each use bumps ``last_used_at`` so the most recently used ones sort first.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    use_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    entries: Mapped[list[MaintenanceEntry]] = relationship(  # noqa: F821
        back_populates="activity"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Activity {self.name!r} used={self.use_count}>"
