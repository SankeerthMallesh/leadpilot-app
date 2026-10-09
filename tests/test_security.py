from app.security import hash_password, verify_password
from tests.conftest import page_token


def test_password_hash_roundtrip():
    h = hash_password("a-long-password-1")
    assert h.startswith("$argon2")
    assert verify_password(h, "a-long-password-1")
    assert not verify_password(h, "wrong")
    assert not verify_password("garbage", "x")


def test_unauthenticated_redirects_to_login(http):
    r = http.get("/clients")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_post_without_csrf_is_rejected(logged_in):
    assert logged_in.post("/logout").status_code == 403
    assert logged_in.post("/assistant/chat", data={"message": "hi"}).status_code == 403


def test_logout_with_csrf(logged_in):
    token = page_token(logged_in)
    r = logged_in.post("/logout", data={"csrf_token": token})
    assert r.status_code == 303
    assert logged_in.get("/clients").status_code == 303
