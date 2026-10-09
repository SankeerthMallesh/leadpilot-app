"""FastAPI application factory."""
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from app import errors
from app.api import assistant, auth, clients, dashboard, setup, studio
from app.config import get_settings
from app.db import engine
from app.logging_setup import configure_logging
from app.middleware import request_context
from app.providers import llm


def create_app() -> FastAPI:
    """Build the app with session cookies, middleware, routers, and static files."""
    s = get_settings()
    configure_logging(s.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN202
        """Preload the local model in the background so the first chat message has no cold start."""
        if s.ollama_warmup and "ollama" in {llm.resolve_provider(None), llm.resolve_provider(s.assistant_provider or None)}:
            threading.Thread(target=llm.warm_up, daemon=True).start()
        yield

    app = FastAPI(title=s.app_name, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.secret_key,
        session_cookie="lp_admin_session",
        max_age=s.session_max_age,
        same_site="lax",
        https_only=s.cookie_secure,
    )
    app.middleware("http")(request_context)
    errors.register(app)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(clients.router)
    app.include_router(studio.router)
    app.include_router(assistant.router)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Liveness: the process is up."""
        return JSONResponse({"status": "ok"})

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        """Readiness: the database answers."""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse({"status": "db_unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app


app = create_app()
