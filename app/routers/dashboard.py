"""Dashboard with due-maintenance overview and recent activity."""

from __future__ import annotations

from datetime import date, timedelta

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
        },
        db=db,
        user=user,
    )


@router.get("/report.pdf")
def plant_report(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chronological full report: entries, measurements and asset changes."""
    plant = db.scalar(select(Asset).where(Asset.type == AssetType.plant))
    entries = list(
        db.scalars(
            select(MaintenanceEntry).options(
                selectinload(MaintenanceEntry.user),
                selectinload(MaintenanceEntry.activity),
                selectinload(MaintenanceEntry.asset),
                selectinload(MaintenanceEntry.images),
            )
        ).all()
    )
    measurements = list(
        db.scalars(select(Measurement).options(selectinload(Measurement.user))).all()
    )
    events = list(
        db.scalars(select(AssetEvent).options(selectinload(AssetEvent.user))).all()
    )

    lang = normalize_lang(request.cookies.get(LANGUAGE_COOKIE))
    pdf = build_plant_report(
        plant.name if plant else "—",
        entries,
        measurements,
        events,
        get_translator(lang),
    )
    filename = f"plant-report_{date.today().isoformat()}"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
