from app.config import get_settings
from app.services import mailer
from tests.conftest import page_token


def _post(http, **fields):
    token = page_token(http)
    return http.post("/assistant/send-email", data=fields, headers={"X-CSRF-Token": token})


def test_disabled_by_default(logged_in, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_email_enabled", False)
    r = _post(logged_in, confirm_send="yes", recipient="a@b.com", subject="Hi", body="Hello")
    assert r.status_code == 503


def test_requires_login(http):
    r = http.post("/assistant/send-email", data={"confirm_send": "yes"})
    assert r.status_code in (303, 403)


def test_requires_confirm_send(logged_in, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_email_enabled", True)
    r = _post(logged_in, recipient="a@b.com", subject="Hi", body="Hello")
    assert r.status_code == 400


def test_sends_once_confirmed(logged_in, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_email_enabled", True)
    calls = []
    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: calls.append((a, k)))
    r = _post(logged_in, confirm_send="yes", recipient="a@b.com", subject="Hi", body="Hello")
    assert r.status_code == 200 and r.json()["sent"] is True
    assert calls == [(("a@b.com", "Hi", "Hello"), {"confirmed": True})]


def test_mailer_error_is_shown(logged_in, monkeypatch):
    monkeypatch.setattr(get_settings(), "chat_email_enabled", True)

    def boom(*_a, **_k):
        raise mailer.MailerError("Replace the SMTP password placeholder in .env.")

    monkeypatch.setattr(mailer, "send_email", boom)
    r = _post(logged_in, confirm_send="yes", recipient="a@b.com", subject="Hi", body="Hello")
    assert r.status_code == 400 and "placeholder" in r.json()["detail"]
