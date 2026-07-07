"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import BASE_DIR, settings


def _make_engine():
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Ensure the parent directory for the SQLite file exists.
        # Format: sqlite:///./data/app.db  ->  ./data/app.db
        db_rel = url.split("///", 1)[-1]
        db_path = (BASE_DIR / db_rel).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Rebuild an absolute URL so it works regardless of CWD.
        url = f"sqlite:///{db_path.as_posix()}"
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped session and closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Import models so they are registered on Base."""
    from app import models  # noqa: F401  (side-effect: registers models)

    Base.metadata.create_all(bind=engine)


def is_sqlite() -> bool:
    return engine.url.get_backend_name() == "sqlite"


def sqlite_file_path() -> Path | None:
    """Absolute path to the SQLite database file, or None for other backends."""
    if not is_sqlite():
        return None
    db = engine.url.database
    if not db or db == ":memory:":
        return None
    return Path(db).resolve()
