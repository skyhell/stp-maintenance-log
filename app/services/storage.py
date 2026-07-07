"""Image upload storage helpers."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/heic",
}


class UploadError(Exception):
    """Raised when an uploaded file is rejected."""


def _safe_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(f"Unsupported file type: {ext or 'unknown'}")
    return ext


async def save_upload(file: UploadFile) -> tuple[str, str]:
    """Validate and store an uploaded image.

    Returns a tuple of (stored_filename, original_filename).
    """
    orig = file.filename or "upload"
    ext = _safe_extension(orig)

    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise UploadError(f"Unsupported content type: {file.content_type}")

    data = await file.read()
    if not data:
        raise UploadError("Empty file")
    if len(data) > settings.max_upload_bytes:
        raise UploadError(
            f"File too large (> {settings.max_upload_mb} MB)"
        )

    stored_name = f"{secrets.token_hex(16)}{ext}"
    dest = settings.upload_path / stored_name
    dest.write_bytes(data)
    return stored_name, orig


def delete_upload(stored_filename: str) -> None:
    """Remove a stored image file if it exists (best effort)."""
    try:
        target = (settings.upload_path / stored_filename).resolve()
        # Guard against path traversal.
        if target.parent == settings.upload_path and target.exists():
            target.unlink()
    except Exception:
        pass
