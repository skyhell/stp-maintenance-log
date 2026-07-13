"""Measurement reading: a process value logged for the plant (e.g. NH4)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # What was measured, e.g. "NH4" — free text, the list builds itself.
    parameter: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Reading of the operating-hours counter (Betriebsstundenzähler).
    operating_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Measurement #{self.id} {self.parameter}={self.value}>"
