"""Create the admin user. Run: python scripts/create_admin.py [--totp]"""
import getpass
import sys

import pyotp

from app.config import get_settings
from app.crypto import encrypt
from app.db import SessionLocal
from app.models.user import User
from app.security import hash_password


def main() -> None:
    email = input("Admin email: ").strip().lower()
    password = getpass.getpass("Password (12+ characters): ")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters.")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    user = User(email=email, password_hash=hash_password(password))
    secret = None
    if "--totp" in sys.argv:
        secret = pyotp.random_base32()
        user.totp_secret_enc = encrypt(secret)
    with SessionLocal() as db:
        db.add(user)
        db.commit()
    print(f"Admin {email} created.")
    if secret:
        uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().app_name)
        print("Add this to your authenticator app (shown once):")
        print(uri)


if __name__ == "__main__":
    main()
