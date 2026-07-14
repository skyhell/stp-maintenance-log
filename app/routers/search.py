"""Global search across maintenance entries, measurements and objects."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.activity import Activity
from app.models.asset import OBJECT_TYPES, Asset
from app.models.maintenance import MaintenanceEntry
from app.models.measurement import Measurement
from app.models.user import User
from app.services.security import get_current_user
from app.services.templating import render

router = APIRouter()

LIMIT = 50


@router.get("/search")
def search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = q.strip()
    entries: list[MaintenanceEntry] = []
    measurements: list[Measurement] = []
    assets: list[Asset] = []

    if q:
        like = f"%{q}%"
        entries = list(
            db.scalars(
                select(MaintenanceEntry)
                .options(
                    selectinload(MaintenanceEntry.asset),
                    selectinload(MaintenanceEntry.activity),
                )
                .outerjoin(Activity, MaintenanceEntry.activity_id == Activity.id)
                .outerjoin(Asset, MaintenanceEntry.asset_id == Asset.id)
                .where(
                    or_(
                        MaintenanceEntry.description.ilike(like),
                        MaintenanceEntry.notes.ilike(like),
                        MaintenanceEntry.comment.ilike(like),
                        Activity.name.ilike(like),
                        Asset.name.ilike(like),
                    )
                )
                .order_by(MaintenanceEntry.occurred_at.desc())
                .limit(LIMIT)
            ).all()
        )
        measurements = list(
            db.scalars(
                select(Measurement)
                .where(Measurement.parameter.ilike(like))
                .order_by(Measurement.measured_at.desc())
                .limit(LIMIT)
            ).all()
        )
        assets = list(
            db.scalars(
                select(Asset)
                .where(Asset.type.in_(OBJECT_TYPES))
                .where(
                    or_(
                        Asset.name.ilike(like),
                        Asset.uid.ilike(like),
                        Asset.address.ilike(like),
                        Asset.comment.ilike(like),
                    )
                )
                .order_by(Asset.name.asc())
                .limit(LIMIT)
            ).all()
        )

    return render(
        request,
        "search.html",
        {
            "q": q,
            "entries": entries,
            "measurements": measurements,
            "assets": assets,
            "total": len(entries) + len(measurements) + len(assets),
        },
        db=db,
        user=user,
    )
