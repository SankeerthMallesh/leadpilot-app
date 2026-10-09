"""Login / logout."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.setup import setup_open
from app.db import get_db
from app.security import authenticate, csrf_token, ip_throttled, verify_csrf
from app.services.audit import audit
from app.web import render

router = APIRouter()


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Show the login form (or the first-run setup page when no admin exists yet)."""
    if setup_open(request, db):
        return RedirectResponse("/setup", status_code=303)
    return render(request, "login.html")


@router.post("/login", dependencies=[Depends(verify_csrf)])
async def login(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Verify credentials, rotate the session, and log in."""
    form = await request.form()
    ip = request.client.host if request.client else "unknown"
    if ip_throttled(ip):
        return render(request, "login.html", status_code=429, error="Too many attempts. Wait and retry.")
    user, error = authenticate(
        db, str(form.get("email", "")), str(form.get("password", "")), str(form.get("totp_code", ""))
    )
    if user is None:
        audit(db, actor="anonymous", action="login_failed", entity_type="user",
              reason=f"failed login from {ip}")
        db.commit()
        return render(request, "login.html", status_code=401, error=error)
    request.session.clear()
    request.session["uid"] = user.id
    request.session["email"] = user.email
    csrf_token(request)
    audit(db, actor=user.email, action="login", entity_type="user", entity_id=user.id, reason="login ok")
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):  # noqa: ANN201
    """Clear the session."""
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
