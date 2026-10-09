"""First-run setup: create the admin account in the browser. Closed as soon as any admin exists."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.user import User
from app.security import csrf_token, hash_password, verify_csrf
from app.services.audit import audit
from app.web import render

router = APIRouter()
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
MIN_PASSWORD = 12


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCAL_HOSTS or get_settings().allow_remote_setup


def has_admin(db: Session) -> bool:
    """True once at least one user exists."""
    return (db.scalar(select(func.count()).select_from(User)) or 0) > 0


def setup_open(request: Request, db: Session) -> bool:
    """The setup page is available only while no admin exists, and only from this computer by default."""
    return _is_local(request) and not has_admin(db)


@router.get("/setup")
def setup_page(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Show the create-admin form."""
    if has_admin(db):
        return RedirectResponse("/login", status_code=303)
    if not _is_local(request):
        return render(request, "setup.html", status_code=403, blocked=True)
    return render(request, "setup.html")


@router.post("/setup", dependencies=[Depends(verify_csrf)])
async def create_admin(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Create the first admin, log in, and go to the dashboard."""
    if has_admin(db):
        return RedirectResponse("/login", status_code=303)
    if not _is_local(request):
        return render(request, "setup.html", status_code=403, blocked=True)
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    error = ""
    if "@" not in email or "." not in email.split("@")[-1] or " " in email:
        error = "Enter a valid email address."
    elif len(password) < MIN_PASSWORD:
        error = f"Password must be at least {MIN_PASSWORD} characters."
    elif password != str(form.get("password2", "")):
        error = "The two passwords do not match."
    if error:
        return render(request, "setup.html", status_code=400, error=error, email=email)
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    audit(db, actor=email, action="admin_created", entity_type="user", entity_id=user.id,
          reason="created in the first-run setup page")
    db.commit()
    request.session.clear()
    request.session["uid"] = user.id
    request.session["email"] = user.email
    csrf_token(request)
    return RedirectResponse("/", status_code=303)
