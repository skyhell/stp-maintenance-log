"""Full backup / restore as a single ZIP (database + uploaded images)."""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app import __version__
from app.config import settings
from app.database import engine, init_db, is_sqlite, sqlite_file_path

DB_ARCNAME = "database/app.db"
UPLOAD_PREFIX = "uploads/"
MANIFEST = "manifest.json"


class BackupError(Exception):
    """Raised when a backup archive is invalid or cannot be restored."""


def create_backup() -> Path:
    """Create a ZIP containing the SQLite DB and all uploads. Returns its path."""
    if not is_sqlite():
        raise BackupError("Automatic backup currently supports SQLite only.")
    db_path = sqlite_file_path()
    if not db_path or not db_path.exists():
        raise BackupError("Database file not found.")

    # Ensure on-disk DB is consistent before copying.
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass

    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out = settings.backup_path / f"backup-{ts}.zip"

    upload_files = [
        p for p in settings.upload_path.glob("*") if p.is_file() and p.name != ".gitkeep"
    ]
    manifest = {
        "app": "stp-maintenance-log",
        "version": __version__,
        "created_at": datetime.now(UTC).isoformat(),
        "upload_count": len(upload_files),
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
        zf.write(db_path, DB_ARCNAME)
        for f in upload_files:
            zf.write(f, f"{UPLOAD_PREFIX}{f.name}")
    return out


def restore_backup(zip_path: Path) -> dict:
    """Restore state from a backup ZIP, replacing DB and uploads.

    The application should be treated as briefly unavailable during restore.
    """
    if not is_sqlite():
        raise BackupError("Automatic restore currently supports SQLite only.")
    if not zipfile.is_zipfile(zip_path):
        raise BackupError("Uploaded file is not a valid ZIP archive.")

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if DB_ARCNAME not in names:
            raise BackupError("Archive does not contain a database file.")
        # Guard against path traversal (Zip Slip).
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise BackupError(f"Unsafe path in archive: {n}")

        manifest = {}
        if MANIFEST in names:
            try:
                manifest = json.loads(zf.read(MANIFEST))
            except Exception:
                manifest = {}

        db_path = sqlite_file_path()
        if db_path is None:
            raise BackupError("Cannot determine database path.")

        # Release all DB connections before overwriting the file.
        engine.dispose()

        # Replace database.
        db_bytes = zf.read(DB_ARCNAME)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove stale WAL/journal side files.
        for side in ("-wal", "-shm", "-journal"):
            sf = Path(str(db_path) + side)
            if sf.exists():
                sf.unlink()
        db_path.write_bytes(db_bytes)

        # Replace uploads directory contents.
        upload_dir = settings.upload_path
        for existing in upload_dir.glob("*"):
            if existing.is_file() and existing.name != ".gitkeep":
                existing.unlink()
            elif existing.is_dir():
                shutil.rmtree(existing, ignore_errors=True)
        restored_uploads = 0
        for n in names:
            if n.startswith(UPLOAD_PREFIX) and not n.endswith("/"):
                target_name = Path(n).name
                if not target_name:
                    continue
                (upload_dir / target_name).write_bytes(zf.read(n))
                restored_uploads += 1

    # Re-create tables if the restored DB is missing any (schema safety).
    init_db()
    return {"restored_uploads": restored_uploads, "manifest": manifest}
