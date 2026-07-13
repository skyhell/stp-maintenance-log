"""Map view (Leaflet + OpenStreetMap) and its JSON data endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.asset import OBJECT_TYPES, Asset, AssetType
from app.models.asset_event import AssetEventAction
from app.models.pipe import PipeSegment
from app.models.user import User
from app.services.asset_events import log_asset_event
from app.services.security import get_current_user, verify_csrf
from app.services.templating import render

router = APIRouter()

_OBJECT_TYPE_VALUES = {t.value for t in OBJECT_TYPES}


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _generate_uid(db: Session, atype: AssetType) -> str:
    """Auto-generate a unique identifier like 'S-3' (shaft) or 'A-7' (connection)."""
    prefix = "S" if atype == AssetType.shaft else "A"
    existing = set(db.scalars(select(Asset.uid)).all())
    n = 1
    while f"{prefix}-{n}" in existing:
        n += 1
    return f"{prefix}-{n}"


@router.get("/map")
def map_view(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render(
        request,
        "map.html",
        {"asset_types": list(AssetType)},
        db=db,
        user=user,
    )


@router.get("/api/assets")
def assets_json(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return assets that have coordinates, for the map markers."""
    assets = db.scalars(
        select(Asset)
        .where(Asset.latitude.is_not(None))
        .where(Asset.longitude.is_not(None))
    ).all()
    return {
        "assets": [
            {
                "id": a.id,
                "uid": a.uid,
                "name": a.name,
                "type": a.type.value,
                "lat": a.latitude,
                "lon": a.longitude,
                "address": a.address,
                "next_maintenance": (
                    a.next_maintenance_date.isoformat()
                    if a.next_maintenance_date
                    else None
                ),
            }
            for a in assets
        ]
    }


@router.get("/api/pipes")
def pipes_json(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Pipe segments (sewer lines) between assets, for the map."""
    pipes = db.scalars(select(PipeSegment)).all()
    return {
        "pipes": [
            {"id": p.id, "from_id": p.from_asset_id, "to_id": p.to_asset_id}
            for p in pipes
        ]
    }


@router.post("/api/pipes")
def create_pipe(
    request: Request,
    csrf_token: str = Form(...),
    from_asset_id: str = Form(...),
    to_asset_id: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Connect two assets with a pipe segment (drawn on the map)."""
    verify_csrf(request, csrf_token)

    if not (from_asset_id.isdigit() and to_asset_id.isdigit()):
        return JSONResponse({"ok": False, "error": "assets"}, status_code=400)
    from_id, to_id = int(from_asset_id), int(to_asset_id)
    if from_id == to_id:
        return JSONResponse({"ok": False, "error": "assets"}, status_code=400)
    if db.get(Asset, from_id) is None or db.get(Asset, to_id) is None:
        return JSONResponse({"ok": False, "error": "assets"}, status_code=400)

    # A segment between the same two assets (either direction) exists only once.
    existing = db.scalar(
        select(PipeSegment).where(
            or_(
                (PipeSegment.from_asset_id == from_id)
                & (PipeSegment.to_asset_id == to_id),
                (PipeSegment.from_asset_id == to_id)
                & (PipeSegment.to_asset_id == from_id),
            )
        )
    )
    if existing:
        return JSONResponse({"ok": False, "error": "exists"}, status_code=400)

    pipe = PipeSegment(from_asset_id=from_id, to_asset_id=to_id)
    db.add(pipe)
    db.commit()
    return {
        "ok": True,
        "pipe": {"id": pipe.id, "from_id": pipe.from_asset_id, "to_id": pipe.to_asset_id},
    }


@router.post("/api/pipes/{pipe_id}/delete")
def delete_pipe(
    pipe_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    pipe = db.get(PipeSegment, pipe_id)
    if pipe:
        db.delete(pipe)
        db.commit()
    return {"ok": True}


@router.post("/api/objects")
def create_object(
    request: Request,
    csrf_token: str = Form(...),
    name: str = Form(...),
    type: str = Form(...),
    latitude: str = Form(...),
    longitude: str = Form(...),
    uid: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a shaft/connection at a location clicked on the map."""
    verify_csrf(request, csrf_token)

    if type not in _OBJECT_TYPE_VALUES:
        return JSONResponse({"ok": False, "error": "type"}, status_code=400)
    atype = AssetType(type)

    lat = _parse_float(latitude)
    lon = _parse_float(longitude)
    if lat is None or lon is None:
        return JSONResponse({"ok": False, "error": "coords"}, status_code=400)

    uid = uid.strip() or _generate_uid(db, atype)
    if db.scalar(select(Asset).where(Asset.uid == uid)):
        return JSONResponse({"ok": False, "error": "uid_taken"}, status_code=400)

    asset = Asset(
        uid=uid,
        name=name.strip() or uid,
        type=atype,
        latitude=lat,
        longitude=lon,
    )
    db.add(asset)
    log_asset_event(db, user.id, asset, AssetEventAction.created)
    db.commit()
    return {
        "ok": True,
        "asset": {
            "id": asset.id,
            "uid": asset.uid,
            "name": asset.name,
            "type": asset.type.value,
            "lat": asset.latitude,
            "lon": asset.longitude,
            "address": asset.address,
            "next_maintenance": None,
        },
    }
