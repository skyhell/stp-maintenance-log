"""Asset model: a plant, channel or connection in the sewage network."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssetType(str, enum.Enum):
    plant = "plant"          # Anlage — the single treatment-plant "head" (singleton)
    shaft = "shaft"          # Schacht (manhole)
    connection = "connection"  # Anschluss


# Object types that users manage on the "Objekte" page (the plant is a singleton
# managed on its own page and is not offered here).
OBJECT_TYPES = (AssetType.shaft, AssetType.connection)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-facing unique identifier (e.g. "PLANT-001"). Unique per object.
    uid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[AssetType] = mapped_column(
        Enum(AssetType), default=AssetType.plant, nullable=False, index=True
    )

    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Recurring maintenance interval; when set, next_maintenance_date is
    # recomputed automatically from the newest maintenance entry.
    maintenance_interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    entries: Mapped[list[MaintenanceEntry]] = relationship(  # noqa: F821
        back_populates="asset"
    )

    # --- Reminder helpers ------------------------------------------------
    def maintenance_status(self, due_soon_days: int) -> str:
        """Return 'overdue', 'due_soon', 'ok' or 'none'."""
        if self.next_maintenance_date is None:
            return "none"
        today = date.today()
        delta = (self.next_maintenance_date - today).days
        if delta < 0:
            return "overdue"
        if delta <= due_soon_days:
            return "due_soon"
        return "ok"

    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Asset {self.uid} {self.name} ({self.type.value})>"
