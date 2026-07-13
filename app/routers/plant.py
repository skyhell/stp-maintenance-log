"""The single treatment plant ('Anlage') — a singleton managed on its own page."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.asset import Asset, AssetType
from app.models.user import User
from app.services.maintenance_schedule import refresh_next_maintenance
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


@router.get("")
def plant_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    plant = _get_plant(db)
    return render(request, "plant.html", {"plant": plant}, db=db, user=user)


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
    db.commit()
    flash(request, "plant.saved")
    return RedirectResponse("/plant", status_code=303)
