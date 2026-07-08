"""Dashboard with due-maintenance overview and recent activity."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.asset import OBJECT_TYPES, Asset
from app.models.maintenance import MaintenanceEntry
from app.models.user import User
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
            "total_assets": total_assets,
            "total_entries": total_entries,
        },
        db=db,
        user=user,
    )
