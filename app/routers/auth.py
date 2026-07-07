"""Authentication routes: login, logout, language switching."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.i18n import LANGUAGE_COOKIE, normalize_lang
from app.services.security import (
    SESSION_PENDING_2FA,
    authenticate,
    login_user,
    logout_user,
    verify_csrf,
)
from app.services.templating import render
from app.services.twofa import verify_and_consume_backup_code, verify_totp

router = APIRouter()


@router.get("/login")
def login_form(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return render(request, "auth/login.html", {"error": None}, db=db)


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    user = authenticate(db, username.strip(), password)
    if not user:
        return render(
            request, "auth/login.html", {"error": "login.error"}, db=db, status_code=401
        )
    if user.totp_enabled and user.totp_secret:
        # Defer the actual login until the second factor is verified.
        request.session[SESSION_PENDING_2FA] = user.id
        return RedirectResponse("/login/2fa", status_code=303)

    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/login/2fa")
def twofa_form(request: Request, db: Session = Depends(get_db)):
    if not request.session.get(SESSION_PENDING_2FA):
        return RedirectResponse("/login", status_code=303)
    return render(request, "auth/twofa.html", {"error": None}, db=db)


@router.post("/login/2fa")
def twofa_submit(
    request: Request,
    code: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    verify_csrf(request, csrf_token)
    pending_id = request.session.get(SESSION_PENDING_2FA)
    if not pending_id:
        return RedirectResponse("/login", status_code=303)
    user = db.get(User, pending_id)
    if not user or not user.totp_enabled:
        request.session.pop(SESSION_PENDING_2FA, None)
        return RedirectResponse("/login", status_code=303)

    ok = verify_totp(user.totp_secret, code)
    if not ok:
        # Fall back to a one-time backup code.
        ok = verify_and_consume_backup_code(user, code)
        if ok:
            db.commit()
    if not ok:
        return render(
            request, "auth/twofa.html", {"error": "twofa.invalid"}, db=db, status_code=401
        )

    request.session.pop(SESSION_PENDING_2FA, None)
    login_user(request, user)
    return RedirectResponse("/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=303)


@router.get("/lang/{lang}")
def set_language(lang: str, request: Request):
    lang = normalize_lang(lang)
    referer = request.headers.get("referer", "/")
    resp = RedirectResponse(referer, status_code=303)
    resp.set_cookie(
        LANGUAGE_COOKIE,
        lang,
        max_age=60 * 60 * 24 * 365,
        samesite="lax",
        httponly=False,
    )
    return resp
