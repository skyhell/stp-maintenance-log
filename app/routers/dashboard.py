"""Dashboard with due-maintenance overview and recent activity."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.database import get_db
from app.models.asset import OBJECT_TYPES, Asset, AssetType
from app.models.asset_event import AssetEvent
from app.models.maintenance import MaintenanceEntry
from app.models.measurement import Measurement
from app.models.user import User
from app.services.i18n import LANGUAGE_COOKIE, get_translator, normalize_lang
from app.services.report import build_plant_report
from app.services.security import get_current_user
from app.services.templating import render

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    today = date.today()
    soon = today + timedelta(days=settings.reminder_due_soon_days)

    overdue = list(
        db.scalars(
            select(Asset)
            .where(Asset.next_maintenance_date.is_not(None))
            .where(Asset.next_maintenance_date < today)
            .order_by(Asset.next_maintenance_date.asc())
        ).all()
    )
    due_soon = list(
        db.scalars(
            select(Asset)
            .where(Asset.next_maintenance_date.is_not(None))
            .where(Asset.next_maintenance_date >= today)
            .where(Asset.next_maintenance_date <= soon)
            .order_by(Asset.next_maintenance_date.asc())
        ).all()
    )

    recent = list(
        db.scalars(
            select(MaintenanceEntry)
            .order_by(MaintenanceEntry.occurred_at.desc())
            .limit(8)
        ).all()
    )

    recent_measurements = list(
        db.scalars(
            select(Measurement).order_by(Measurement.measured_at.desc()).limit(8)
        ).all()
    )

    total_assets = (
        db.scalar(select(func.count(Asset.id)).where(Asset.type.in_(OBJECT_TYPES))) or 0
    )
    total_entries = db.scalar(select(func.count(MaintenanceEntry.id))) or 0

    return render(
        request,
        "dashboard.html",
        {
            "overdue": overdue,
            "due_soon": due_soon,
            "recent": recent,
            "recent_measurements": recent_measurements,
            "total_assets": total_assets,
            "total_entries": total_entries,
            "report_years": _data_years(db),
        },
        db=db,
        user=user,
    )


def _data_years(db: Session) -> list[int]:
    """Years covered by any data, newest first, for the report quick select."""
    mins = [
        db.scalar(select(func.min(MaintenanceEntry.occurred_at))),
        db.scalar(select(func.min(Measurement.measured_at))),
        db.scalar(select(func.min(AssetEvent.occurred_at))),
    ]
    first = min((m.year for m in mins if m is not None), default=date.today().year)
    return list(range(date.today().year, first - 1, -1))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/report.pdf")
def plant_report(
    request: Request,
    year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chronological full report: entries, measurements and asset changes.

    Time range: a quick-select ``year`` wins over explicit ``date_from``/
    ``date_to``; with neither given the report covers everything.
    """
    if year and year.isdigit():
        y = int(year)
        df, dt_ = date(y, 1, 1), date(y, 12, 31)
    else:
        df, dt_ = _parse_date(date_from), _parse_date(date_to)
    start = datetime.combine(df, time.min, UTC) if df else None
    end = datetime.combine(dt_, time.max, UTC) if dt_ else None

    def in_range(stmt, column):
        if start is not None:
            stmt = stmt.where(column >= start)
        if end is not None:
            stmt = stmt.where(column <= end)
        return stmt

    plant = db.scalar(select(Asset).where(Asset.type == AssetType.plant))
    entries = list(
        db.scalars(
            in_range(
                select(MaintenanceEntry).options(
                    selectinload(MaintenanceEntry.user),
                    selectinload(MaintenanceEntry.activity),
                    selectinload(MaintenanceEntry.asset),
                    selectinload(MaintenanceEntry.images),
                ),
                MaintenanceEntry.occurred_at,
            )
        ).all()
    )
    measurements = list(
        db.scalars(
            in_range(
                select(Measurement).options(selectinload(Measurement.user)),
                Measurement.measured_at,
            )
        ).all()
    )
    events = list(
        db.scalars(
            in_range(
                select(AssetEvent).options(selectinload(AssetEvent.user)),
                AssetEvent.occurred_at,
            )
        ).all()
    )
    object_counts = {
        "shafts": db.scalar(
            select(func.count(Asset.id)).where(Asset.type == AssetType.shaft)
        )
        or 0,
        "connections": db.scalar(
            select(func.count(Asset.id)).where(Asset.type == AssetType.connection)
        )
        or 0,
    }

    lang = normalize_lang(request.cookies.get(LANGUAGE_COOKIE))
    pdf = build_plant_report(
        plant,
        object_counts,
        entries,
        measurements,
        events,
        get_translator(lang),
        range_from=df,
        range_to=dt_,
    )
    filename = f"plant-report_{date.today().isoformat()}"
    if year and year.isdigit():
        filename = f"plant-report_{year}"
    elif df or dt_:
        from_part = df.isoformat() if df else "start"
        to_part = dt_.isoformat() if dt_ else "end"
        filename = f"plant-report_{from_part}_{to_part}"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
