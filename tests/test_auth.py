import re

from tests.conftest import PASSWORD


def _login(http, email, password):
    page = http.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    return http.post("/login", data={"email": email, "password": password, "csrf_token": token})


def test_login_ok(http, admin):
    assert _login(http, admin.email, PASSWORD).status_code == 303
    assert http.get("/clients").status_code == 200


def test_login_wrong_password(http, admin):
    assert _login(http, admin.email, "nope-nope-nope").status_code == 401


def test_account_locks_after_max_attempts(http, admin):
    for _ in range(5):
        assert _login(http, admin.email, "bad-password-x").status_code == 401
    r = _login(http, admin.email, PASSWORD)
    assert r.status_code == 401
    assert "locked" in r.text.lower()


def test_login_without_csrf_rejected(http, admin):
    r = http.post("/login", data={"email": admin.email, "password": PASSWORD})
    assert r.status_code == 403
