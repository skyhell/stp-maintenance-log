"""Object management: create, edit, delete shafts (Schacht) and connections.

The single treatment plant ('Anlage') is a singleton managed separately in
``routers/plant.py`` and is intentionally not editable here.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.asset import OBJECT_TYPES, Asset, AssetType
from app.models.asset_event import AssetEventAction
from app.models.maintenance import MaintenanceEntry
from app.models.pipe import PipeSegment
from app.models.user import User
from app.services.asset_events import log_asset_event, snapshot
from app.services.maintenance_schedule import refresh_next_maintenance
from app.services.security import get_current_user, verify_csrf
from app.services.templating import flash, render

router = APIRouter(prefix="/assets")

_OBJECT_TYPE_VALUES = {t.value for t in OBJECT_TYPES}


def _coerce_object_type(value: str) -> AssetType:
    """Only shaft/connection are valid here; anything else falls back to shaft."""
    return AssetType(value) if value in _OBJECT_TYPE_VALUES else AssetType.shaft


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


def _parse_interval(value: str | None) -> int | None:
    if value is None or not value.strip().isdigit():
        return None
    months = int(value.strip())
    return months if months > 0 else None


@router.get("")
def list_assets(
    request: Request,
    type: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Only managed objects (shaft/connection); the plant lives on its own page.
    stmt = (
        select(Asset)
        .where(Asset.type.in_(OBJECT_TYPES))
        .order_by(Asset.next_maintenance_date.asc().nulls_last())
    )
    if type in _OBJECT_TYPE_VALUES:
        stmt = stmt.where(Asset.type == AssetType(type))
    assets = list(db.scalars(stmt).all())

    # Entry counts per asset for display.
    counts = dict(
        db.execute(
            select(MaintenanceEntry.asset_id, func.count(MaintenanceEntry.id)).group_by(
                MaintenanceEntry.asset_id
            )
        ).all()
    )
    return render(
        request,
        "assets/list.html",
        {
            "assets": assets,
            "counts": counts,
            "filter_type": type or "",
            "asset_types": list(OBJECT_TYPES),
        },
        db=db,
        user=user,
    )


@router.get("/new")
def new_asset(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render(
        request,
        "assets/form.html",
        {"asset": None, "asset_types": list(OBJECT_TYPES)},
        db=db,
        user=user,
    )


@router.post("/new")
def create_asset(
    request: Request,
    csrf_token: str = Form(...),
    uid: str = Form(...),
    name: str = Form(...),
    type: str = Form(...),
    install_date: str = Form(""),
    next_maintenance_date: str = Form(""),
    maintenance_interval_months: str = Form(""),
    address: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    uid = uid.strip()
    existing = db.scalar(select(Asset).where(Asset.uid == uid))
    if existing:
        return render(
            request,
            "assets/form.html",
            {
                "asset": None,
                "asset_types": list(OBJECT_TYPES),
                "error": "asset.uid",
                "form": {"uid": uid, "name": name},
            },
            db=db,
            user=user,
            status_code=400,
        )

    asset = Asset(
        uid=uid,
        name=name.strip(),
        type=_coerce_object_type(type),
        install_date=_parse_date(install_date),
        next_maintenance_date=_parse_date(next_maintenance_date),
        maintenance_interval_months=_parse_interval(maintenance_interval_months),
        address=address.strip() or None,
        latitude=_parse_float(latitude),
        longitude=_parse_float(longitude),
        comment=comment.strip() or None,
    )
    db.add(asset)
    log_asset_event(db, user.id, asset, AssetEventAction.created)
    db.commit()
    flash(request, "asset.saved")
    return RedirectResponse("/assets", status_code=303)


@router.get("/{asset_id}/edit")
def edit_asset(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.type == AssetType.plant:
        # The plant is edited on its dedicated page.
        return RedirectResponse("/plant", status_code=303)
    return render(
        request,
        "assets/form.html",
        {"asset": asset, "asset_types": list(OBJECT_TYPES)},
        db=db,
        user=user,
    )


@router.post("/{asset_id}/edit")
def update_asset(
    asset_id: int,
    request: Request,
    csrf_token: str = Form(...),
    uid: str = Form(...),
    name: str = Form(...),
    type: str = Form(...),
    install_date: str = Form(""),
    next_maintenance_date: str = Form(""),
    maintenance_interval_months: str = Form(""),
    address: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    comment: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.type == AssetType.plant:
        return RedirectResponse("/plant", status_code=303)

    uid = uid.strip()
    clash = db.scalar(select(Asset).where(Asset.uid == uid, Asset.id != asset_id))
    if clash:
        return render(
            request,
            "assets/form.html",
            {"asset": asset, "asset_types": list(OBJECT_TYPES), "error": "asset.uid"},
            db=db,
            user=user,
            status_code=400,
        )

    before = snapshot(asset)
    asset.uid = uid
    asset.name = name.strip()
    asset.type = _coerce_object_type(type)
    asset.install_date = _parse_date(install_date)
    asset.next_maintenance_date = _parse_date(next_maintenance_date)
    asset.maintenance_interval_months = _parse_interval(maintenance_interval_months)
    asset.address = address.strip() or None
    asset.latitude = _parse_float(latitude)
    asset.longitude = _parse_float(longitude)
    asset.comment = comment.strip() or None
    refresh_next_maintenance(db, asset.id)
    log_asset_event(db, user.id, asset, AssetEventAction.updated, before)
    db.commit()
    flash(request, "asset.saved")
    return RedirectResponse("/assets", status_code=303)


@router.post("/{asset_id}/delete")
def delete_asset(
    asset_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    asset = db.get(Asset, asset_id)
    if asset and asset.type == AssetType.plant:
        # The singleton plant cannot be deleted.
        flash(request, "error.forbidden", "error")
        return RedirectResponse("/assets", status_code=303)
    if asset:
        # Detach entries from the asset rather than deleting the history.
        for entry in list(asset.entries):
            entry.asset_id = None
        # Pipe segments make no sense without both endpoints.
        db.execute(
            delete(PipeSegment).where(
                or_(
                    PipeSegment.from_asset_id == asset_id,
                    PipeSegment.to_asset_id == asset_id,
                )
            )
        )
        log_asset_event(db, user.id, asset, AssetEventAction.deleted)
        db.delete(asset)
        db.commit()
        flash(request, "asset.deleted")
    return RedirectResponse("/assets", status_code=303)
