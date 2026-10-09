"""Template rendering helper shared by all routers."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import __version__, markdown_lite
from app.config import get_settings
from app.providers import llm
from app.security import csrf_token

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["md"] = markdown_lite.render


def flash(request: Request, message: str, kind: str = "ok") -> None:
    """Queue a one-time message for the next page."""
    request.session.setdefault("flash", []).append({"kind": kind, "text": message})


def render(request: Request, name: str, status_code: int = 200, **ctx):  # noqa: ANN201
    """Render a template with the common context (CSRF, flash, AI panel scope)."""
    client = ctx.get("client")
    ctx.update(
        csrf_token=csrf_token(request),
        flash_messages=request.session.pop("flash", []),
        app_name=get_settings().app_name,
        app_version=__version__,
        dry_run=get_settings().dry_run,
        user_email=request.session.get("email"),
        assistant_client_id=client.id if client is not None else None,
        current_path=request.url.path,
        ai_warm="ollama" in {llm.resolve_provider(None), llm.resolve_provider(get_settings().assistant_provider or None)},
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
