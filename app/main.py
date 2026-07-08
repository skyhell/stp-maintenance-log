"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.config import BASE_DIR, settings
from app.database import SessionLocal, init_db
from app.models.user import User, UserRole
from app.routers import account, admin, assets, auth, dashboard, entries, plant
from app.routers import map as map_router
from app.services.security import get_current_user, hash_password
from app.services.templating import render

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("stp_maintenance")

STATIC_DIR = BASE_DIR / "app" / "static"


def _bootstrap_admin() -> None:
    """Create an initial admin account if the users table is empty."""
    with SessionLocal() as db:
        count = db.scalar(select(func.count(User.id))) or 0
        if count == 0:
            admin_user = User(
                username=settings.bootstrap_admin_username,
                password_hash=hash_password(settings.bootstrap_admin_password),
                role=UserRole.admin,
            )
            db.add(admin_user)
            db.commit()
            logger.warning(
                "Created bootstrap admin '%s'. CHANGE THE PASSWORD after first login!",
                settings.bootstrap_admin_username,
            )


def _migrate_asset_types() -> None:
    """Rename the legacy 'channel' asset type to 'shaft' in existing databases."""
    from sqlalchemy import text

    from app.database import engine

    with engine.begin() as conn:
        conn.execute(text("UPDATE assets SET type='shaft' WHERE type='channel'"))


def _bootstrap_plant() -> None:
    """Ensure the single treatment-plant ('Anlage') record exists."""
    from app.models.asset import Asset, AssetType

    with SessionLocal() as db:
        count = db.scalar(
            select(func.count(Asset.id)).where(Asset.type == AssetType.plant)
        ) or 0
        if count == 0:
            db.add(
                Asset(
                    uid="ANLAGE",
                    name="Kläranlage",
                    type=AssetType.plant,
                )
            )
            db.commit()
            logger.info("Created the initial treatment-plant record ('Anlage').")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database ...")
    init_db()
    _migrate_asset_types()
    _bootstrap_admin()
    _bootstrap_plant()
    # Ensure data directories exist.
    settings.upload_path  # noqa: B018
    settings.backup_path  # noqa: B018
    logger.info("Application ready (v%s)", __version__)
    yield


app = FastAPI(title="Sewage Treatment Plant Maintenance Log", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="stp_session",
    https_only=settings.secure_cookies,
    same_site="lax",
    max_age=60 * 60 * 24 * 7,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Authenticated media (uploaded images) --------------------------------
@app.get("/media/{filename}")
def media(
    filename: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    # Guard against path traversal: only serve files directly in upload_path.
    target = (settings.upload_path / filename).resolve()
    if target.parent != settings.upload_path or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


# --- Routers --------------------------------------------------------------
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(entries.router)
app.include_router(assets.router)
app.include_router(plant.router)
app.include_router(map_router.router)
app.include_router(account.router)
app.include_router(admin.router)


# --- Error handling -------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Redirect unauthenticated users to the login page for HTML requests.
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html and exc.status_code in (403, 404):
        key = "error.forbidden" if exc.status_code == 403 else "error.not_found"
        return render(
            request,
            "error.html",
            {"status_code": exc.status_code, "message_key": key},
            status_code=exc.status_code,
        )
    return RedirectResponse("/", status_code=303) if accepts_html else _json_error(exc)


def _json_error(exc: HTTPException):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}
