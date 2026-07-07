"""Maintenance log entry and its attached images."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MaintenanceEntry(Base):
    __tablename__ = "maintenance_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("assets.id"), nullable=True, index=True
    )
    activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("activities.id"), nullable=True, index=True
    )

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user: Mapped[User] = relationship(back_populates="entries")  # noqa: F821
    asset: Mapped[Asset | None] = relationship(back_populates="entries")  # noqa: F821
    activity: Mapped[Activity | None] = relationship(back_populates="entries")  # noqa: F821
    images: Mapped[list[EntryImage]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MaintenanceEntry #{self.id} at {self.occurred_at}>"


class EntryImage(Base):
    __tablename__ = "entry_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_entries.id"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # stored name on disk
    orig_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entry: Mapped[MaintenanceEntry] = relationship(back_populates="images")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EntryImage {self.filename}>"
