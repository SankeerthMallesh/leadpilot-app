"""HTML/JSON error handling that keeps auth redirects and HTMX redirects working."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.web import templates

logger = logging.getLogger("leadpilot.errors")

TITLES = {
    403: ("Not allowed", "Your session may have expired. Reload the page and try again."),
    404: ("Page not found", "That page or record doesn't exist."),
    429: ("Slow down", "Too many requests. Wait a moment and try again."),
    500: ("Something went wrong", "The error was logged. Try again, and quote the request ID if it persists."),
}


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "") and not request.headers.get("hx-request")


def _page(request: Request, status: int, detail: str | None = None) -> Response:
    title, message = TITLES.get(status, ("Error", "Something went wrong."))
    return templates.TemplateResponse(
        request, "error.html",
        {"status": status, "title": title, "message": detail if status == 400 and detail else message,
         "request_id": getattr(request.state, "request_id", ""), "app_name": get_settings().app_name},
        status_code=status,
    )


def register(app: FastAPI) -> None:
    """Install exception handlers."""

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        headers = exc.headers or {}
        if exc.status_code == 303 and "Location" in headers:
            return RedirectResponse(headers["Location"], status_code=303)
        if "HX-Redirect" in headers:
            return Response(status_code=exc.status_code, headers=headers)
        if _wants_html(request):
            return _page(request, exc.status_code, str(exc.detail))
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled exception", extra={"extra_fields": {
            "request_id": getattr(request.state, "request_id", ""), "path": request.url.path}})
        if _wants_html(request):
            return _page(request, 500)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
