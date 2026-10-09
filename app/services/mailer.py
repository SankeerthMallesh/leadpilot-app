"""Send one plain-text email over SMTP. Used only after the operator explicitly confirms."""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("leadpilot.mailer")

_ADDRESS = re.compile(r"^[^\s@<>,;:]+@[^\s@<>,;:]+\.[^\s@<>,;:]+$")


class MailerError(Exception):
    """A problem the operator can fix; the message is safe to show in the UI."""


def clean_password(raw: str) -> str:
    """Google shows app passwords in groups of four; remove all whitespace."""
    return "".join((raw or "").split())


def send_email(recipient: str, subject: str, body: str, *, confirmed: bool = False) -> None:
    """Send one email. Raises MailerError with a readable message on any problem."""
    if not confirmed:
        raise MailerError("Explicit confirmation is required before sending.")
    s = get_settings()
    if not s.smtp_host or not s.smtp_user:
        raise MailerError("Email is not set up. Add SMTP_HOST and SMTP_USER to .env, then restart.")
    password = clean_password(s.smtp_password)
    if not password or password.lower().startswith("your-"):
        raise MailerError("Replace the SMTP password placeholder in .env.")

    recipient = (recipient or "").strip()
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not _ADDRESS.match(recipient) or len(recipient) > 254:
        raise MailerError("Enter a valid recipient email address.")
    if not subject or "\n" in subject or "\r" in subject or len(subject) > 200:
        raise MailerError("Enter a valid subject (one line, up to 200 characters).")
    if not body:
        raise MailerError("The email body cannot be empty.")
    if len(body) > 20000:
        raise MailerError("The email body is too long (20,000 characters maximum).")

    message = EmailMessage()
    message["From"] = s.smtp_from or s.smtp_user
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        context = ssl.create_default_context()
        if s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=context) as server:
                server.login(s.smtp_user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(s.smtp_user, password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        logger.warning("smtp login rejected: %s", exc)
        raise MailerError(
            "The mail server rejected the login. Check SMTP_USER, and for Gmail use a 16-character "
            "App Password (needs 2-Step Verification), not your normal password."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        logger.warning("smtp recipient refused: %s", exc)
        raise MailerError("The mail server refused that recipient address.") from exc
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("smtp send failed: %s: %s", type(exc).__name__, exc)
        raise MailerError(
            f"Email delivery failed ({type(exc).__name__}). Check SMTP_HOST, SMTP_PORT and your internet connection."
        ) from exc


def status() -> tuple[str, bool]:
    """Human-readable email readiness for the System page, plus whether it is OK."""
    s = get_settings()
    if not s.chat_email_enabled:
        return "off (CHAT_EMAIL_ENABLED=false)", True
    password = clean_password(s.smtp_password)
    if not s.smtp_host or not s.smtp_user:
        return "needs SMTP_HOST and SMTP_USER in .env", False
    if not password or password.lower().startswith("your-"):
        return "needs the SMTP password in .env", False
    return "ready", True
