"""Password hashing, CSRF tokens and authentication dependencies."""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole

_hasher = PasswordHasher()

# Session keys
SESSION_USER_ID = "user_id"
SESSION_CSRF = "csrf_token"
SESSION_PENDING_2FA = "pending_2fa_user_id"  # used in Step 2


# --- Password hashing -----------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return False


# --- CSRF -----------------------------------------------------------------
def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_CSRF)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_CSRF] = token
    return token


def verify_csrf(request: Request, submitted: str | None) -> None:
    expected = request.session.get(SESSION_CSRF)
    if not expected or not submitted or not secrets.compare_digest(expected, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token invalid or missing"
        )


# --- Authentication helpers ----------------------------------------------
def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    return user


def login_user(request: Request, user: User) -> None:
    request.session[SESSION_USER_ID] = user.id
    # Rotate CSRF token on privilege change.
    request.session[SESSION_CSRF] = secrets.token_urlsafe(32)


def logout_user(request: Request) -> None:
    request.session.clear()


def _current_user_or_none(request: Request, db: Session) -> User | None:
    uid = request.session.get(SESSION_USER_ID)
    if not uid:
        return None
    user = db.get(User, uid)
    if not user or not user.is_active:
        return None
    return user


# --- FastAPI dependencies -------------------------------------------------
def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    return _current_user_or_none(request, db)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _current_user_or_none(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def generate_backup_codes(n: int = 10) -> list[str]:
    """Generate human-friendly one-time backup codes (Step 2)."""
    return [f"{secrets.randbelow(10**8):08d}" for _ in range(n)]
