"""Dashboard, costs, and system status pages."""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import engine, get_db
from app.providers import llm
from app.security import require_admin
from app.services import icp as icp_service
from app.services import mailer, reporting
from app.web import render

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Home dashboard."""
    return render(request, "dashboard.html", stats=reporting.dashboard(db),
                  api_ready=bool(get_settings().anthropic_api_key) or llm.active_provider() == "ollama")


@router.get("/costs")
def costs(request: Request, db: Session = Depends(get_db)):  # noqa: ANN201
    """Paid-API spend this month."""
    return render(request, "costs.html", c=reporting.costs_overview(db))


@router.get("/system")
def system(request: Request):  # noqa: ANN201
    """Read-only configuration and health checks (never shows secrets)."""
    s = get_settings()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    ollama_row: dict = {}
    if "ollama" in {llm.resolve_provider(None), llm.resolve_provider(s.assistant_provider or None)}:
        h = llm.ollama_health()
        state = ("not reachable: " + h["error"]) if not h["reachable"] else (
            "model not installed (ollama pull " + s.ollama_model + ")" if not h["installed"]
            else ("model loaded in memory" if h["loaded"] else "reachable, model not loaded yet"))
        ollama_row = {"Ollama": (state, f"v{h['version']}, {s.ollama_model}" if h["version"] else s.ollama_model,
                                 h["reachable"] and h["installed"])}
    prompts = sorted(p.stem for p in Path(icp_service.PROMPTS_DIR).glob("*.md"))
    email_state, email_ok = mailer.status()
    return render(request, "system.html", info={
        "Database": ("ok" if db_ok else "unreachable", engine.dialect.name, db_ok),
        "AI provider": (llm.active_provider(), f"AI panel: {llm.resolve_provider(s.assistant_provider or None)}", True),
        **ollama_row,
        "Anthropic API key": ("configured" if s.anthropic_api_key else "missing", "", bool(s.anthropic_api_key)),
        "Main model": (s.claude_model_main, "", True),
        "Fast model": (s.claude_model_fast, "", True),
        "Operator email": (email_state, s.smtp_host if s.chat_email_enabled else "", email_ok),
        "Dry run": ("on (no real emails)" if s.dry_run else "OFF", "", s.dry_run),
        "Secure cookies": ("on" if s.cookie_secure else "off (use HTTPS in production)", "", s.cookie_secure),
        "App URL": (s.app_url, "", True),
        "Monthly budget": (f"${s.monthly_budget_usd:,.2f}", "", True),
    }, prompts=prompts)
