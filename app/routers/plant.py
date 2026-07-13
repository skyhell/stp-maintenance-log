"""The single treatment plant ('Anlage') — a singleton managed on its own page."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.asset import Asset, AssetType
from app.models.asset_event import AssetEvent, AssetEventAction
from app.models.maintenance import MaintenanceEntry
from app.models.measurement import Measurement
from app.models.user import User
from app.services.asset_events import log_asset_event, snapshot
from app.services.i18n import LANGUAGE_COOKIE, get_translator, normalize_lang
from app.services.maintenance_schedule import refresh_next_maintenance
from app.services.report import build_plant_report
from app.services.security import require_admin, verify_csrf
from app.services.templating import flash, render

router = APIRouter(prefix="/plant")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _get_plant(db: Session) -> Asset:
    """Return the singleton plant, creating a default one if missing."""
    plant = db.scalar(
        select(Asset).where(Asset.type == AssetType.plant).order_by(Asset.id)
    )
    if plant is None:
        plant = Asset(uid="ANLAGE", name="Kläranlage", type=AssetType.plant)
        db.add(plant)
        db.commit()
    return plant


def _data_years(db: Session) -> list[int]:
    """Years covered by any data, newest first, for the report quick select."""
    mins = [
        db.scalar(select(func.min(MaintenanceEntry.occurred_at))),
        db.scalar(select(func.min(Measurement.measured_at))),
        db.scalar(select(func.min(AssetEvent.occurred_at))),
    ]
    first = min((m.year for m in mins if m is not None), default=date.today().year)
    return list(range(date.today().year, first - 1, -1))


@router.get("")
def plant_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    plant = _get_plant(db)
    return render(
        request,
        "plant.html",
        {"plant": plant, "report_years": _data_years(db)},
        db=db,
        user=user,
    )


@router.get("/report.pdf")
def plant_report(
    request: Request,
    year: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
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

    plant = _get_plant(db)
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


@router.post("")
def update_plant(
    request: Request,
    csrf_token: str = Form(...),
    name: str = Form(...),
    install_date: str = Form(""),
    next_maintenance_date: str = Form(""),
    maintenance_interval_months: str = Form(""),
    address: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    plant = _get_plant(db)
    before = snapshot(plant)
    plant.name = name.strip() or plant.name
    plant.install_date = _parse_date(install_date)
    plant.next_maintenance_date = _parse_date(next_maintenance_date)
    interval = maintenance_interval_months.strip()
    plant.maintenance_interval_months = (
        int(interval) if interval.isdigit() and int(interval) > 0 else None
    )
    plant.address = address.strip() or None
    plant.latitude = _parse_float(latitude)
    plant.longitude = _parse_float(longitude)
    plant.comment = comment.strip() or None
    refresh_next_maintenance(db, plant.id)
    log_asset_event(db, user.id, plant, AssetEventAction.updated, before)
    db.commit()
    flash(request, "plant.saved")
    return RedirectResponse("/plant", status_code=303)
