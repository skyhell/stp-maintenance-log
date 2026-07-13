"""Asset change log: records create/update/delete of objects and the plant."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssetEventAction(str, enum.Enum):
    created = "created"
    updated = "updated"
    deleted = "deleted"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AssetEvent(Base):
    __tablename__ = "asset_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True, nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    # uid/name are copied so the event survives deletion of the asset.
    asset_uid: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[AssetEventAction] = mapped_column(Enum(AssetEventAction), nullable=False)

    # JSON list of [i18n_key, old, new] triples for updates; None otherwise.
    changes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User | None] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AssetEvent {self.action.value} {self.asset_uid}>"
