"""Password hashing, session auth, CSRF, and login throttling."""
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt
from app.db import get_db
from app.models.base import as_utc
from app.models.user import User
from app.ratelimit import SlidingWindowLimiter

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-a-real-password")

_ip_limiter = SlidingWindowLimiter(max_events=20, window_seconds=15 * 60)


def hash_password(password: str) -> str:
    """Argon2id hash."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Constant-effort password check."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def ip_throttled(ip: str) -> bool:
    """True if this IP exceeded the login attempt limit (per process)."""
    return not _ip_limiter.allow(ip)


def authenticate(db: Session, email: str, password: str, totp_code: str) -> tuple[User | None, str]:
    """Check credentials with account lockout. Returns (user, error_message)."""
    s = get_settings()
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        verify_password(_DUMMY_HASH, password)  # equalize timing
        return None, "Invalid email or password."
    locked = as_utc(user.locked_until)
    if locked and locked > datetime.now(UTC):
        return None, "Account temporarily locked. Try again later."
    ok = verify_password(user.password_hash, password)
    if ok and user.totp_secret_enc:
        ok = pyotp.TOTP(decrypt(user.totp_secret_enc)).verify(totp_code.strip(), valid_window=1)
    if not ok:
        user.failed_logins += 1
        if user.failed_logins >= s.login_max_attempts:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=s.login_lockout_minutes)
            user.failed_logins = 0
        db.commit()
        return None, "Invalid email or password."
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return user, ""


def csrf_token(request: Request) -> str:
    """Return (creating if needed) the session's CSRF token."""
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency: reject state-changing requests without a valid CSRF token."""
    sent = request.headers.get("x-csrf-token")
    if not sent:
        form = await request.form()
        sent = form.get("csrf_token")
    expected = request.session.get("csrf")
    if not expected or not sent or not hmac.compare_digest(str(sent), expected):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency: the logged-in admin, or redirect to /login."""
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or not user.is_active:
        if request.headers.get("hx-request"):
            raise HTTPException(status_code=401, headers={"HX-Redirect": "/login"})
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user
