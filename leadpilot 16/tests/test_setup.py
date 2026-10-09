import re

from sqlalchemy import select

from app.api import setup as setup_api
from app.models.user import User

GOOD = {"email": "me@example.com", "password": "a-long-password-1", "password2": "a-long-password-1"}


def _token(http):
    page = http.get("/setup")
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)


def test_setup_creates_admin_and_logs_in(http, db, monkeypatch):
    monkeypatch.setattr(setup_api, "LOCAL_HOSTS", {"testclient"})
    r = http.post("/setup", data={**GOOD, "csrf_token": _token(http)})
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert db.scalar(select(User).where(User.email == "me@example.com")) is not None
    assert http.get("/clients").status_code == 200


def test_login_page_points_to_setup_when_no_admin(http, monkeypatch):
    monkeypatch.setattr(setup_api, "LOCAL_HOSTS", {"testclient"})
    r = http.get("/login")
    assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_setup_is_closed_once_an_admin_exists(http, admin, monkeypatch):
    monkeypatch.setattr(setup_api, "LOCAL_HOSTS", {"testclient"})
    assert http.get("/setup").headers["location"] == "/login"
    assert http.get("/login").status_code == 200


def test_setup_refused_from_other_computers(http):
    assert http.get("/setup").status_code == 403


def test_setup_rejects_short_or_mismatched_passwords(http, db, monkeypatch):
    monkeypatch.setattr(setup_api, "LOCAL_HOSTS", {"testclient"})
    token = _token(http)
    short = http.post("/setup", data={"email": "me@example.com", "password": "short", "password2": "short", "csrf_token": token})
    assert short.status_code == 400
    other = http.post("/setup", data={**GOOD, "password2": "different-password-9", "csrf_token": token})
    assert other.status_code == 400
    assert db.scalar(select(User)) is None
