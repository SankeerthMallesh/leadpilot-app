import smtplib
from types import SimpleNamespace

import pytest

from app.services import mailer


def _settings(**over):
    base = {"smtp_host": "smtp.test", "smtp_port": 587, "smtp_user": "me@test.com",
            "smtp_password": "abcd efgh ijkl mnop", "smtp_from": "", "chat_email_enabled": True}
    base.update(over)
    return SimpleNamespace(**base)


class FakeSMTP:
    sent: list = []
    logged_in: tuple | None = None
    login_error: Exception | None = None

    def __init__(self, host, port, timeout=0):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error
        FakeSMTP.logged_in = (user, password)

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def _fake_smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logged_in, FakeSMTP.login_error = [], None, None
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer, "get_settings", _settings)


def test_requires_confirmation():
    with pytest.raises(mailer.MailerError, match="confirmation"):
        mailer.send_email("a@b.com", "Hi", "Hello")
    assert FakeSMTP.sent == []


def test_sends_and_strips_spaces_from_app_password():
    mailer.send_email("a@b.com", "Hi", "Hello there", confirmed=True)
    assert FakeSMTP.logged_in == ("me@test.com", "abcdefghijklmnop")
    msg = FakeSMTP.sent[0]
    assert msg["To"] == "a@b.com" and msg["Subject"] == "Hi" and msg["From"] == "me@test.com"


@pytest.mark.parametrize("password", ["", "your-16-letter-app-password", "  "])
def test_placeholder_password_is_rejected(monkeypatch, password):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_password=password))
    with pytest.raises(mailer.MailerError, match="placeholder"):
        mailer.send_email("a@b.com", "Hi", "Hello", confirmed=True)


def test_missing_host_is_explained(monkeypatch):
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_host=""))
    with pytest.raises(mailer.MailerError, match="SMTP_HOST"):
        mailer.send_email("a@b.com", "Hi", "Hello", confirmed=True)


@pytest.mark.parametrize("recipient", ["", "nope", "a@b", "a b@c.com", "a@b.com\nBcc: x@y.com"])
def test_bad_recipient_rejected(recipient):
    with pytest.raises(mailer.MailerError, match="recipient"):
        mailer.send_email(recipient, "Hi", "Hello", confirmed=True)


def test_header_injection_in_subject_rejected():
    with pytest.raises(mailer.MailerError, match="subject"):
        mailer.send_email("a@b.com", "Hi\r\nBcc: x@y.com", "Hello", confirmed=True)


def test_empty_body_rejected():
    with pytest.raises(mailer.MailerError, match="body"):
        mailer.send_email("a@b.com", "Hi", "   ", confirmed=True)


def test_login_rejection_gives_a_useful_message():
    FakeSMTP.login_error = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    with pytest.raises(mailer.MailerError, match="App Password"):
        mailer.send_email("a@b.com", "Hi", "Hello", confirmed=True)


def test_status_text(monkeypatch):
    assert mailer.status() == ("ready", True)
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(smtp_password="your-16-letter-app-password"))
    assert mailer.status()[1] is False
    monkeypatch.setattr(mailer, "get_settings", lambda: _settings(chat_email_enabled=False))
    assert mailer.status()[1] is True
