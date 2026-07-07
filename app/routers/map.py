"""Map view (Leaflet + OpenStreetMap) and its JSON data endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.asset import Asset, AssetType
from app.models.user import User
from app.services.security import get_current_user
from app.services.templating import render

router = APIRouter()


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
