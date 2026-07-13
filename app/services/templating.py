"""Jinja2 template configuration and a shared render helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import __version__
from app.config import settings
from app.models.user import User
from app.services.i18n import LANGUAGE_COOKIE, get_translator, normalize_lang
from app.services.security import (
    SESSION_USER_ID,
    get_or_create_csrf_token,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["app_version"] = __version__


def _fmt_date(value) -> str:
    """Display dates as dd/mm/YYYY everywhere."""
    return value.strftime("%d/%m/%Y") if value else ""


def _fmt_datetime(value) -> str:
    """Display datetimes as dd/mm/YYYY HH:MM (24h) everywhere."""
    return value.strftime("%d/%m/%Y %H:%M") if value else ""


templates.env.filters["dmy"] = _fmt_date
templates.env.filters["dmy_hm"] = _fmt_datetime


def current_lang(request: Request) -> str:
    return normalize_lang(request.cookies.get(LANGUAGE_COOKIE))


def _current_user(request: Request, db: Session | None) -> User | None:
    if db is None:
        return None
    uid = request.session.get(SESSION_USER_ID)
    if not uid:
        return None
    return db.get(User, uid)


def render(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    *,
    db: Session | None = None,
    user: User | None = None,
    status_code: int = 200,
):
    """Render a template with the common context every page needs."""
    lang = current_lang(request)
    if user is None:
        user = _current_user(request, db)

    base_context: dict[str, Any] = {
        "request": request,
        "t": get_translator(lang),
        "lang": lang,
        "supported_languages": settings.supported_languages,
        "current_user": user,
        "csrf_token": get_or_create_csrf_token(request),
        "settings": settings,
        "flash": request.session.pop("_flash", None),
    }
    if context:
        base_context.update(context)
    return templates.TemplateResponse(
        request, template_name, base_context, status_code=status_code
    )


def flash(request: Request, message: str, category: str = "success") -> None:
    """Store a one-shot flash message shown on the next rendered page."""
    request.session["_flash"] = {"message": message, "category": category}
