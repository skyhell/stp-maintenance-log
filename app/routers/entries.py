"""Maintenance entries: history view with filters, create, edit, delete."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.asset import Asset
from app.models.maintenance import EntryImage, MaintenanceEntry
from app.models.user import User
from app.services.activities import get_or_create_activity, list_activities
from app.services.i18n import LANGUAGE_COOKIE, get_translator, normalize_lang
from app.services.pdf_export import build_history_pdf
from app.services.security import get_current_user, verify_csrf
from app.services.storage import UploadError, delete_upload, save_upload
from app.services.templating import flash, render

router = APIRouter(prefix="/entries")


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


def _filtered_entries(
    db: Session,
    asset_id: str | None,
    q: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[list[MaintenanceEntry], int | None]:
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

    df = _parse_date(date_from)
    dt_ = _parse_date(date_to)
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
    return list(db.scalars(stmt).all()), selected_asset


@router.get("")
def history(
    request: Request,
    asset_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries, selected_asset = _filtered_entries(db, asset_id, q, date_from, date_to)
    assets = list(db.scalars(select(Asset).order_by(Asset.name)).all())

    return render(
        request,
        "entries/list.html",
        {
            "entries": entries,
            "assets": assets,
            "filters": {
                "asset_id": selected_asset,
                "q": q or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
        db=db,
        user=user,
    )


@router.get("/export.pdf")
def export_pdf(
    request: Request,
    asset_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    entries, _ = _filtered_entries(db, asset_id, q, date_from, date_to)
    lang = normalize_lang(request.cookies.get(LANGUAGE_COOKIE))
    pdf = build_history_pdf(
        entries,
        get_translator(lang),
        _parse_date(date_from),
        _parse_date(date_to),
    )
    filename = "maintenance-history"
    if date_from or date_to:
        filename += f"_{date_from or 'start'}_{date_to or 'end'}"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
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
    asset_id: str = Form(""),
    activity: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    comment: str = Form(""),
    images: list[UploadFile] = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)

    activity_obj = get_or_create_activity(db, activity)
    entry = MaintenanceEntry(
        occurred_at=_parse_dt(occurred_at) or datetime.now(UTC),
        user_id=user.id,
        asset_id=int(asset_id) if asset_id.isdigit() else None,
        activity_id=activity_obj.id if activity_obj else None,
        description=description.strip() or None,
        notes=notes.strip() or None,
        comment=comment.strip() or None,
    )
    db.add(entry)
    db.flush()
    if images:
        await _handle_images(db, entry, images)
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
    asset_id: str = Form(""),
    activity: str = Form(""),
    description: str = Form(""),
    notes: str = Form(""),
    comment: str = Form(""),
    images: list[UploadFile] = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    entry = db.get(MaintenanceEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    activity_obj = get_or_create_activity(db, activity)
    entry.occurred_at = _parse_dt(occurred_at) or entry.occurred_at
    entry.asset_id = int(asset_id) if asset_id.isdigit() else None
    entry.activity_id = activity_obj.id if activity_obj else None
    entry.description = description.strip() or None
    entry.notes = notes.strip() or None
    entry.comment = comment.strip() or None
    if images:
        await _handle_images(db, entry, images)
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
        for img in entry.images:
            delete_upload(img.filename)
        db.delete(entry)
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
