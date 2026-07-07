"""Account self-service: change own password (2FA added in Step 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.security import (
    generate_backup_codes,
    get_current_user,
    hash_password,
    verify_csrf,
    verify_password,
)
from app.services.templating import flash, render
from app.services.twofa import (
    generate_secret,
    hash_backup_codes,
    provisioning_uri,
    qr_data_uri,
    remaining_backup_codes,
    verify_totp,
)

router = APIRouter(prefix="/account")

SESSION_SETUP_SECRET = "setup_totp_secret"


@router.get("")
def account(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return render(
        request,
        "account.html",
        {"remaining_codes": remaining_backup_codes(user)},
        db=db,
        user=user,
    )


@router.post("/password")
def change_password(
    request: Request,
    csrf_token: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    error = None
    if not verify_password(current_password, user.password_hash):
        error = "account.wrong_password"
    elif new_password != confirm_password:
        error = "account.password_mismatch"
    elif len(new_password) < 8:
        error = "account.password_mismatch"

    if error:
        return render(
            request, "account.html", {"error": error}, db=db, user=user, status_code=400
        )

    user.password_hash = hash_password(new_password)
    db.commit()
    flash(request, "account.password_changed")
    return RedirectResponse("/account", status_code=303)


# --- Two-factor authentication -------------------------------------------
@router.get("/2fa/setup")
def twofa_setup(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.totp_enabled:
        return RedirectResponse("/account", status_code=303)
    # Generate (or reuse) a pending secret held only in the session until
    # the user proves they can produce a valid code.
    secret = request.session.get(SESSION_SETUP_SECRET)
    if not secret:
        secret = generate_secret()
        request.session[SESSION_SETUP_SECRET] = secret
    uri = provisioning_uri(user.username, secret)
    return render(
        request,
        "account_2fa_setup.html",
        {"secret": secret, "qr": qr_data_uri(uri)},
        db=db,
        user=user,
    )


@router.post("/2fa/enable")
def twofa_enable(
    request: Request,
    csrf_token: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    secret = request.session.get(SESSION_SETUP_SECRET)
    if not secret or not verify_totp(secret, code):
        uri = provisioning_uri(user.username, secret or generate_secret())
        return render(
            request,
            "account_2fa_setup.html",
            {"secret": secret, "qr": qr_data_uri(uri), "error": "twofa.invalid"},
            db=db,
            user=user,
            status_code=400,
        )

    codes = generate_backup_codes(10)
    user.totp_secret = secret
    user.totp_enabled = True
    user.backup_codes = hash_backup_codes(codes)
    db.commit()
    request.session.pop(SESSION_SETUP_SECRET, None)
    # Show the plaintext backup codes exactly once.
    return render(
        request,
        "account_2fa_codes.html",
        {"codes": codes},
        db=db,
        user=user,
    )


@router.post("/2fa/disable")
def twofa_disable(
    request: Request,
    csrf_token: str = Form(...),
    current_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    if not verify_password(current_password, user.password_hash):
        flash(request, "account.wrong_password", "error")
        return RedirectResponse("/account", status_code=303)
    user.totp_enabled = False
    user.totp_secret = None
    user.backup_codes = None
    db.commit()
    flash(request, "twofa.disabled")
    return RedirectResponse("/account", status_code=303)


@router.post("/2fa/backup-codes")
def twofa_regen_codes(
    request: Request,
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    verify_csrf(request, csrf_token)
    if not user.totp_enabled:
        return RedirectResponse("/account", status_code=303)
    codes = generate_backup_codes(10)
    user.backup_codes = hash_backup_codes(codes)
    db.commit()
    return render(request, "account_2fa_codes.html", {"codes": codes}, db=db, user=user)
