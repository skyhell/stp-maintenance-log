"""Maintenance entries: history view with filters, create, edit, delete."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.asset import Asset
from app.models.maintenance import EntryImage, MaintenanceEntry
from app.models.user import User
from app.services.activities import get_or_create_activity, list_activities
from app.services.i18n import LANGUAGE_COOKIE, get_translator, normalize_lang
from app.services.maintenance_schedule import refresh_next_maintenance
from app.services.security import get_current_user, verify_csrf
from app.services.storage import UploadError, delete_upload, save_upload
from app.services.templating import flash, render

router = APIRouter(prefix="/entries")

PER_PAGE = 25


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


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


def _combine_dt(raw: str, date_part: str, time_part: str) -> str:
    """Join separate date + time inputs; a full datetime string wins."""
    if raw:
        return raw
    if not date_part:
        return ""
    return f"{date_part}T{time_part}" if time_part else date_part


def _data_years(db: Session) -> list[int]:
    """Years covered by entries, newest first, for the quick select."""
    first_dt = db.scalar(select(func.min(MaintenanceEntry.occurred_at)))
    first = first_dt.year if first_dt is not None else date.today().year
    return list(range(date.today().year, first - 1, -1))


def _filtered_entries(
    db: Session,
    asset_id: str | None,
    activity_id: str | None,
    year: str | None,
    q: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[MaintenanceEntry], int | None, int | None]:
    stmt = (
        select(MaintenanceEntry)
        .options(
            selectinload(MaintenanceEntry.asset),
            selectinload(MaintenanceEntry.activity),
            selectinload(MaintenanceEntry.user),
            selectinload(MaintenanceEntry.images),
        )
        .order_by(MaintenanceEntry.occurred_at.desc())
    )

    selected_asset = None
    if asset_id and asset_id.isdigit():
        selected_asset = int(asset_id)
        stmt = stmt.where(MaintenanceEntry.asset_id == selected_asset)

    selected_activity = None
    if activity_id and activity_id.isdigit():
        selected_activity = int(activity_id)
        stmt = stmt.where(MaintenanceEntry.activity_id == selected_activity)

    # Quick-select year wins over an explicit from/to range (like the report).
    if year and year.isdigit():
        y = int(year)
        df, dt_ = date(y, 1, 1), date(y, 12, 31)
    else:
        df, dt_ = _parse_date(date_from), _parse_date(date_to)
    if df:
        stmt = stmt.where(
            MaintenanceEntry.occurred_at >= datetime.combine(df, time.min, UTC)
        )
    if dt_:
        stmt = stmt.where(
            MaintenanceEntry.occurred_at <= datetime.combine(dt_, time.max, UTC)
        )
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                MaintenanceEntry.description.ilike(like),
                MaintenanceEntry.notes.ilike(like),
                MaintenanceEntry.comment.ilike(like),
            )
        )
    return list(db.scalars(stmt).all()), selected_asset, selected_activity


@router.get("")
def history(
    request: Request,
    asset_id: str | None = None,
    activity_id: str | None = None,
    year: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries, selected_asset, selected_activity = _filtered_entries(
        db, asset_id, activity_id, year, q, date_from, date_to
    )
    assets = list(db.scalars(select(Asset).order_by(Asset.name)).all())

    total = len(entries)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, page), pages)
    page_items = entries[(page - 1) * PER_PAGE : page * PER_PAGE]

    return render(
        request,
        "entries/list.html",
        {
            "entries": page_items,
            "assets": assets,
            "activities": list_activities(db),
            "years": _data_years(db),
            "page": page,
            "pages": pages,
            "filters": {
                "asset_id": selected_asset,
                "activity_id": selected_activity,
                "year": year if year and year.isdigit() else "",
                "q": q or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
        db=db,
        user=user,
    )


@router.get("/export.csv")
def export_csv(
    request: Request,
    asset_id: str | None = None,
    activity_id: str | None = None,
    year: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries, _, _ = _filtered_entries(
        db, asset_id, activity_id, year, q, date_from, date_to
    )
    t = get_translator(normalize_lang(request.cookies.get(LANGUAGE_COOKIE)))

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(
        [
            t("entry.datetime"),
            t("entry.user"),
            t("entry.activity"),
            t("entry.asset"),
            t("entry.operating_hours"),
            t("entry.description"),
            t("entry.notes"),
            t("entry.comment"),
            t("entry.images"),
        ]
    )
    for e in entries:
        writer.writerow(
            [
                e.occurred_at.strftime("%d/%m/%Y %H:%M"),
                e.user.username if e.user else "",
                e.activity.name if e.activity else "",
                f"{e.asset.name} ({e.asset.uid})" if e.asset else "",
                e.operating_hours if e.operating_hours is not None else "",
                e.description or "",
                e.notes or "",
                e.comment or "",
                len(e.images),
            ]
        )
    bom = "﻿"
    return Response(
        content=bom + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="maintenance-entries.csv"'},
    )


@router.get("/new")
def new_entry(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render(
        request,
        "entries/form.html",
        {
            "entry": None,
            "assets": list(db.scalars(select(Asset).order_by(Asset.name)).all()),
            "activities": list_activities(db),
            "now": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        },
        db=db,
        user=user,
    )


def _render_form_error(
    request: Request,
    db: Session,
    user: User,
    entry: MaintenanceEntry | None,
    occurred_at: str,
    form: dict,
):
    """Re-render the entry form with an error, keeping what the user typed."""
    return render(
        request,
        "entries/form.html",
        {
            "entry": entry,
            "assets": list(db.scalars(select(Asset).order_by(Asset.name)).all()),
            "activities": list_activities(db),
            "now": occurred_at or datetime.now().strftime("%Y-%m-%dT%H:%M"),
            "error": "entry.operating_hours_required",
            "form": form,
        },
        db=db,
        user=user,
        status_code=400,
    )


async def _handle_images(db: Session, entry: MaintenanceEntry, files: list[UploadFile]):
    for f in files:
        if not f or not f.filename:
            continue
        try:
            stored, orig = await save_upload(f)
        except UploadError:
            continue
        db.add(EntryImage(entry_id=entry.id, filename=stored, orig_name=orig))


@router.post("/new")
async def create_entry(
    request: Request,
    csrf_token: str = Form(...),
    occurred_at: str = Form(""),
    occurred_date: str = Form(""),
    occurred_time: str = Form(""),
    asset_id: str = Form(""),
    activity: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    comment: str = Form(""),
    operating_hours: str = Form(""),
    images: list[UploadFile] = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    occurred_at = _combine_dt(occurred_at, occurred_date, occurred_time)

    operating_hours_f = _parse_float(operating_hours)
    if operating_hours_f is None:
        form = {
            "asset_id": int(asset_id) if asset_id.isdigit() else None,
            "activity": activity,
            "description": description,
            "notes": notes,
            "comment": comment,
            "operating_hours": operating_hours,
        }
        return _render_form_error(request, db, user, None, occurred_at, form)

    activity_obj = get_or_create_activity(db, activity)
    entry = MaintenanceEntry(
        occurred_at=_parse_dt(occurred_at) or datetime.now(UTC),
        user_id=user.id,
        asset_id=int(asset_id) if asset_id.isdigit() else None,
        activity_id=activity_obj.id if activity_obj else None,
        description=description.strip() or None,
        notes=notes.strip() or None,
        comment=comment.strip() or None,
        operating_hours=operating_hours_f,
    )
    db.add(entry)
    db.flush()
    if images:
        await _handle_images(db, entry, images)
    refresh_next_maintenance(db, entry.asset_id)
    db.commit()
    flash(request, "entry.saved")
    return RedirectResponse("/entries", status_code=303)


@router.get("/{entry_id}/edit")
def edit_entry(
    entry_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entry = db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return render(
        request,
        "entries/form.html",
        {
            "entry": entry,
            "assets": list(db.scalars(select(Asset).order_by(Asset.name)).all()),
            "activities": list_activities(db),
            "now": entry.occurred_at.strftime("%Y-%m-%dT%H:%M"),
        },
        db=db,
        user=user,
    )


@router.post("/{entry_id}/edit")
async def update_entry(
    entry_id: int,
    request: Request,
    csrf_token: str = Form(...),
    occurred_at: str = Form(""),
    occurred_date: str = Form(""),
    occurred_time: str = Form(""),
    asset_id: str = Form(""),
    activity: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    comment: str = Form(""),
    operating_hours: str = Form(""),
    images: list[UploadFile] = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    occurred_at = _combine_dt(occurred_at, occurred_date, occurred_time)
    entry = db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    operating_hours_f = _parse_float(operating_hours)
    if operating_hours_f is None:
        form = {
            "asset_id": int(asset_id) if asset_id.isdigit() else None,
            "activity": activity,
            "description": description,
            "notes": notes,
            "comment": comment,
            "operating_hours": operating_hours,
        }
        return _render_form_error(request, db, user, entry, occurred_at, form)

    activity_obj = get_or_create_activity(db, activity)
    old_asset_id = entry.asset_id
    entry.occurred_at = _parse_dt(occurred_at) or entry.occurred_at
    entry.asset_id = int(asset_id) if asset_id.isdigit() else None
    entry.activity_id = activity_obj.id if activity_obj else None
    entry.description = description.strip() or None
    entry.notes = notes.strip() or None
    entry.comment = comment.strip() or None
    entry.operating_hours = operating_hours_f
    if images:
        await _handle_images(db, entry, images)
    db.flush()
    refresh_next_maintenance(db, entry.asset_id)
    if old_asset_id != entry.asset_id:
        refresh_next_maintenance(db, old_asset_id)
    db.commit()
    flash(request, "entry.saved")
    return RedirectResponse("/entries", status_code=303)


@router.post("/{entry_id}/delete")
def delete_entry(
    entry_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    entry = db.get(MaintenanceEntry, entry_id)
    if entry:
        asset_id = entry.asset_id
        for img in entry.images:
            delete_upload(img.filename)
        db.delete(entry)
        db.flush()
        refresh_next_maintenance(db, asset_id)
        db.commit()
        flash(request, "entry.deleted")
    return RedirectResponse("/entries", status_code=303)


@router.post("/image/{image_id}/delete")
def delete_image(
    image_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    img = db.get(EntryImage, image_id)
    entry_id = img.entry_id if img else None
    if img:
        delete_upload(img.filename)
        db.delete(img)
        db.commit()
    if entry_id:
        return RedirectResponse(f"/entries/{entry_id}/edit", status_code=303)
    return RedirectResponse("/entries", status_code=303)
