"""Admin: user management (create, edit, delete, reset password)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.services.backup import BackupError, create_backup, restore_backup
from app.services.security import hash_password, require_admin, verify_csrf
from app.services.templating import flash, render

logger = logging.getLogger("stp_maintenance")

router = APIRouter(prefix="/admin")


@router.get("/users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = list(db.scalars(select(User).order_by(User.username)).all())
    return render(
        request,
        "admin/users.html",
        {"users": users, "roles": list(UserRole)},
        db=db,
        user=admin,
    )


@router.post("/users/new")
def create_user(
    request: Request,
    csrf_token: str = Form(...),
    username: str = Form(...),
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form("user"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    username = username.strip()
    if not username or len(password) < 8:
        flash(request, "error.generic", "error")
        return RedirectResponse("/admin/users", status_code=303)
    if db.scalar(select(User).where(User.username == username)):
        flash(request, "error.generic", "error")
        return RedirectResponse("/admin/users", status_code=303)

    user = User(
        username=username,
        email=email.strip() or None,
        password_hash=hash_password(password),
        role=UserRole(role) if role in (r.value for r in UserRole) else UserRole.user,
    )
    db.add(user)
    db.commit()
    flash(request, "asset.saved")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/edit")
def edit_user(
    user_id: int,
    request: Request,
    csrf_token: str = Form(...),
    email: str = Form(""),
    role: str = Form("user"),
    is_active: str = Form(""),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.email = email.strip() or None
    if role in (r.value for r in UserRole):
        # Prevent an admin from demoting the last remaining admin.
        if user.role == UserRole.admin and role != "admin":
            admin_count = len(
                db.scalars(select(User).where(User.role == UserRole.admin)).all()
            )
            if admin_count <= 1:
                flash(request, "error.generic", "error")
                return RedirectResponse("/admin/users", status_code=303)
        user.role = UserRole(role)
    user.is_active = is_active == "on"
    if new_password:
        if len(new_password) >= 8:
            user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, "asset.saved")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    user = db.get(User, user_id)
    if not user:
        return RedirectResponse("/admin/users", status_code=303)
    if user.id == admin.id:
        flash(request, "error.generic", "error")
        return RedirectResponse("/admin/users", status_code=303)
    if user.role == UserRole.admin:
        admin_count = len(
            db.scalars(select(User).where(User.role == UserRole.admin)).all()
        )
        if admin_count <= 1:
            flash(request, "error.generic", "error")
            return RedirectResponse("/admin/users", status_code=303)
    # Keep the maintenance history: entries remain but reference a deleted user.
    # Reassign entries to the acting admin to preserve foreign keys.
    for entry in list(user.entries):
        entry.user_id = admin.id
    db.delete(user)
    db.commit()
    flash(request, "asset.deleted")
    return RedirectResponse("/admin/users", status_code=303)


# --- Backup / Restore -----------------------------------------------------
@router.get("/backup")
def backup_page(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return render(request, "admin/backup.html", {}, db=db, user=admin)


@router.post("/backup/download")
def backup_download(
    request: Request,
    csrf_token: str = Form(...),
    admin: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    try:
        path = create_backup()
    except BackupError as exc:
        logger.error("Backup failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        path, media_type="application/zip", filename=path.name
    )


@router.post("/backup/restore")
async def backup_restore(
    request: Request,
    csrf_token: str = Form(...),
    archive: UploadFile = File(...),
    admin: User = Depends(require_admin),
):
    verify_csrf(request, csrf_token)
    fd, tmp_name = tempfile.mkstemp(suffix=".zip")
    os.close(fd)  # close immediately so Windows can delete it later
    tmp = Path(tmp_name)
    try:
        tmp.write_bytes(await archive.read())
        result = restore_backup(tmp)
        logger.warning(
            "Restore complete: %s uploads restored", result.get("restored_uploads")
        )
    except BackupError as exc:
        logger.error("Restore failed: %s", exc)
        flash(request, "backup.restore_error", "error")
        return RedirectResponse("/admin/backup", status_code=303)
    finally:
        tmp.unlink(missing_ok=True)
    flash(request, "backup.restore_ok")
    return RedirectResponse("/admin/backup", status_code=303)
