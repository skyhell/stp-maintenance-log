"""Helpers to record asset (object/plant) changes in the change log."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_event import AssetEvent, AssetEventAction

# Tracked fields with the i18n label key used when rendering the report.
_TRACKED = (
    ("uid", "asset.uid"),
    ("name", "asset.name"),
    ("type", "asset.type"),
    ("install_date", "asset.install_date"),
    ("next_maintenance_date", "asset.next_maintenance"),
    ("maintenance_interval_months", "asset.interval"),
    ("address", "asset.address"),
    ("latitude", "asset.latitude"),
    ("longitude", "asset.longitude"),
    ("comment", "asset.comment"),
)


def _display(field: str, value) -> str:
    if value is None or value == "":
        return "—"
    if field == "type":
        return value.value if hasattr(value, "value") else str(value)
    if field in ("install_date", "next_maintenance_date"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def snapshot(asset: Asset) -> dict[str, str]:
    """Capture the tracked fields as display strings (taken before an edit)."""
    return {field: _display(field, getattr(asset, field)) for field, _ in _TRACKED}


def log_asset_event(
    db: Session,
    user_id: int | None,
    asset: Asset,
    action: AssetEventAction,
    before: dict[str, str] | None = None,
) -> None:
    """Record a create/update/delete; a diff-less update is not logged."""
    changes = None
    if action == AssetEventAction.updated and before is not None:
        after = snapshot(asset)
        diff = [
            [label_key, before[field], after[field]]
            for field, label_key in _TRACKED
            if before[field] != after[field]
        ]
        if not diff:
            return
        changes = json.dumps(diff, ensure_ascii=False)

    db.add(
        AssetEvent(
            user_id=user_id,
            asset_uid=asset.uid,
            asset_name=asset.name,
            action=action,
            changes=changes,
        )
    )
