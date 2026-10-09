"""AI panel endpoints: streaming chat (primary), plain chat, history, clear."""
import json
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models.client import Client
from app.models.user import User
from app.providers import llm
from app.ratelimit import SlidingWindowLimiter
from app.security import require_admin, verify_csrf
from app.services import assistant as assistant_service
from app.services import mailer as mailer_service
from app.services.audit import audit
from app.services.costs import BudgetExceeded
from app.web import templates

router = APIRouter(prefix="/assistant", dependencies=[Depends(require_admin)])
_chat_limiter = SlidingWindowLimiter(get_settings().chat_rate_per_minute, 60)
_email_limiter = SlidingWindowLimiter(10, 60)  # at most 10 operator emails per minute
SLOW_MESSAGE = "You're sending messages quickly. Wait a few seconds and try again."
WARM_INTERVAL_SECONDS = 60.0
_last_warm = 0.0
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _scope(db: Session, raw: str | None) -> Client | None:
    if not raw:
        return None
    try:
        client = db.get(Client, int(raw))
    except ValueError:
        raise HTTPException(400, "Bad client id") from None
    if client is None:
        raise HTTPException(404, "Client not found")
    return client


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload) + "\n\n"


def _error_stream(message: str) -> StreamingResponse:
    return StreamingResponse(iter([_sse({"t": "error", "x": message})]), media_type="text/event-stream",
                             headers=SSE_HEADERS)


@router.get("/history")
def get_history(request: Request, client_id: str | None = None, db: Session = Depends(get_db),
                user: User = Depends(require_admin)):  # noqa: ANN201
    """Load this scope's chat history into the panel."""
    client = _scope(db, client_id)
    rows = assistant_service.history(db, user, client.id if client else None)
    return templates.TemplateResponse(request, "partials/assistant_messages.html", {"messages": rows})


@router.post("/stream", dependencies=[Depends(verify_csrf)])
async def stream(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):  # noqa: ANN201
    """Stream the AI's reply as server-sent events; the partial reply is saved if the operator stops."""
    form = await request.form()
    regenerate = str(form.get("regenerate", "")) == "1"
    message = str(form.get("message", "")).strip()
    if not regenerate and not message:
        raise HTTPException(400, "Empty message")
    if not _chat_limiter.allow(str(user.id)):
        return _error_stream(SLOW_MESSAGE)
    client = _scope(db, str(form.get("client_id", "")) or None)
    try:
        prepared = assistant_service.prepare(db, user, message, client, str(form.get("page_path", "")), regenerate)
    except (BudgetExceeded, ValueError) as exc:
        return _error_stream(str(exc))
    user_id = user.id

    def events() -> Iterator[str]:
        parts: list[str] = []
        usage = None
        error = ""
        stopped = False
        try:
            try:
                for kind, value in llm.stream(system=prepared.system, messages=prepared.turns,
                                              model=prepared.model, max_tokens=1200,
                                              provider=prepared.provider):
                    if kind == "delta":
                        parts.append(value)
                        yield _sse({"t": "delta", "x": value})
                    else:
                        usage = value
            except GeneratorExit:
                stopped = True
                raise
            except llm.LLMNotConfigured:
                error = f"The AI isn't configured yet. {llm.not_configured_hint(prepared.provider)}"
                yield _sse({"t": "error", "x": error})
            except llm.LLMError as exc:
                error = f"Sorry, the AI request failed: {exc}"
                yield _sse({"t": "error", "x": error})
        finally:
            text = "".join(parts)
            if not text and not error and not stopped:
                error = "The model returned an empty reply. Please try again."
                yield _sse({"t": "error", "x": error})
            if text and stopped:
                text += "\n\n(stopped)"
            with SessionLocal() as own_db:
                assistant_service.finalize(own_db, prepared, user_id, text or error or "(stopped)", usage)
        yield _sse({"t": "done"})

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat", dependencies=[Depends(verify_csrf)])
async def chat(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):  # noqa: ANN201
    """Non-streaming chat (returns both message bubbles as HTML)."""
    form = await request.form()
    message = str(form.get("message", "")).strip()
    if not message:
        raise HTTPException(400, "Empty message")
    if not _chat_limiter.allow(str(user.id)):
        slow = SimpleNamespace(role="assistant", content=SLOW_MESSAGE)
        return templates.TemplateResponse(request, "partials/assistant_messages.html", {"messages": [slow]})
    client = _scope(db, str(form.get("client_id", "")) or None)
    # ask() makes a blocking HTTP call; run it off the event loop so other requests are not frozen
    pair = await run_in_threadpool(assistant_service.ask, db, user, message, client,
                                   str(form.get("page_path", "")))
    return templates.TemplateResponse(request, "partials/assistant_messages.html", {"messages": list(pair)})


@router.post("/clear", dependencies=[Depends(verify_csrf)])
async def clear(request: Request, db: Session = Depends(get_db), user: User = Depends(require_admin)):  # noqa: ANN201
    """Clear this scope's chat history."""
    form = await request.form()
    client = _scope(db, str(form.get("client_id", "")) or None)
    assistant_service.clear_history(db, user, client.id if client else None)
    return templates.TemplateResponse(request, "partials/assistant_messages.html", {"messages": []})


@router.post("/send-email", dependencies=[Depends(verify_csrf)])
async def send_email_route(request: Request, db: Session = Depends(get_db),
                           user: User = Depends(require_admin)) -> JSONResponse:
    """Send one email after explicit operator confirmation (field confirm_send=yes)."""
    if not get_settings().chat_email_enabled:
        raise HTTPException(503, "Email sending is turned off. Set CHAT_EMAIL_ENABLED=true in .env and restart.")
    form = await request.form()
    if str(form.get("confirm_send", "")).strip().lower() != "yes":
        raise HTTPException(400, "Explicit confirmation is required before sending.")
    if not _email_limiter.allow(str(user.id)):
        raise HTTPException(429, "Too many emails in a minute. Wait a moment and try again.")
    recipient = str(form.get("recipient", "")).strip()
    subject = str(form.get("subject", "")).strip()
    body = str(form.get("body", "")).strip()
    try:
        await run_in_threadpool(mailer_service.send_email, recipient, subject, body, confirmed=True)
    except mailer_service.MailerError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit(db, actor=user.email, action="email_sent", entity_type="email", reason=f"operator email to {recipient}")
    db.commit()
    return JSONResponse({"sent": True, "message": "Email sent successfully."})


@router.post("/warm", dependencies=[Depends(verify_csrf)])
async def warm() -> JSONResponse:
    """Fire-and-forget: load the Ollama model into memory when the panel opens (at most once a minute)."""
    global _last_warm
    s = get_settings()
    now = time.monotonic()
    if "ollama" not in {llm.resolve_provider(None), llm.resolve_provider(s.assistant_provider or None)} \
            or now - _last_warm < WARM_INTERVAL_SECONDS:
        return JSONResponse({"warming": False})
    _last_warm = now
    threading.Thread(target=llm.warm_up, daemon=True).start()
    return JSONResponse({"warming": True})
