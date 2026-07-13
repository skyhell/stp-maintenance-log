"""Pipe segment: a sewer line drawn between two assets on the map."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PipeSegment(Base):
    __tablename__ = "pipe_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"), nullable=False, index=True
    )
    to_asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    from_asset: Mapped[Asset] = relationship(foreign_keys=[from_asset_id])  # noqa: F821
    to_asset: Mapped[Asset] = relationship(foreign_keys=[to_asset_id])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PipeSegment #{self.id} {self.from_asset_id}->{self.to_asset_id}>"
