"""Encryption at rest (Fernet / MultiFernet). Reused for OAuth tokens in Phase 2."""
import base64
import hashlib

from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings


def _fernet() -> MultiFernet:
    s = get_settings()
    keys = [k.strip() for k in s.token_encryption_keys.split(",") if k.strip()]
    if not keys:
        derived = hashlib.sha256(b"leadpilot-enc:" + s.secret_key.encode()).digest()
        keys = [base64.urlsafe_b64encode(derived).decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(plain: str) -> str:
    """Encrypt a string with the newest key."""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a string with any configured key."""
    return _fernet().decrypt(token.encode()).decode()
