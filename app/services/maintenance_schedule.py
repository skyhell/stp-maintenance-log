"""Automatic maintenance scheduling from per-asset intervals."""

from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.maintenance import MaintenanceEntry


def add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day to the target month's length."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def refresh_next_maintenance(db: Session, asset_id: int | None) -> None:
    """Recompute an asset's next maintenance date from its newest entry.

    Only acts when the asset has a maintenance interval and at least one
    entry; otherwise the (manually maintained) date is left untouched.
    """
    if asset_id is None:
        return
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.maintenance_interval_months:
        return
    latest = db.scalar(
        select(func.max(MaintenanceEntry.occurred_at)).where(
            MaintenanceEntry.asset_id == asset_id
        )
    )
    if latest is None:
        return
    asset.next_maintenance_date = add_months(
        latest.date(), asset.maintenance_interval_months
    )
