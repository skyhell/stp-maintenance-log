"""TOTP two-factor authentication helpers (Google Authenticator / Authy)."""

from __future__ import annotations

import base64
import io

import pyotp
import qrcode

from app.models.user import User
from app.services.security import hash_password, verify_password

ISSUER = "STP Maintenance Log"


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(username: str, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def qr_data_uri(uri: str) -> str:
    """Render the provisioning URI as a base64 PNG data URI for <img src>."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


# --- Backup codes ---------------------------------------------------------
def hash_backup_codes(codes: list[str]) -> str:
    """Store backup codes as newline-separated argon2 hashes."""
    return "\n".join(hash_password(c) for c in codes)


def verify_and_consume_backup_code(user: User, code: str) -> bool:
    """Check a backup code; if valid, remove it so it can't be reused.

    Mutates ``user.backup_codes`` in place. The caller must commit the session.
    """
    if not user.backup_codes:
        return False
    code = code.strip().replace(" ", "")
    hashes = [h for h in user.backup_codes.split("\n") if h]
    for h in hashes:
        if verify_password(code, h):
            hashes.remove(h)
            user.backup_codes = "\n".join(hashes)
            return True
    return False


def remaining_backup_codes(user: User) -> int:
    if not user.backup_codes:
        return 0
    return len([h for h in user.backup_codes.split("\n") if h])
