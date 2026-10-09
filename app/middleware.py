"""Request ID, structured access log, and security headers."""
import logging
import time
import uuid

from fastapi import Request

from app.config import get_settings

logger = logging.getLogger("leadpilot.access")


async def request_context(request: Request, call_next):  # noqa: ANN001, ANN201
    """Attach a request id, log one JSON line per request, add security headers."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("unhandled error", extra={"extra_fields": {
            "request_id": request_id, "method": request.method, "path": request.url.path}})
        raise
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if get_settings().cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    level = logging.DEBUG if request.url.path.startswith(("/static", "/healthz", "/readyz")) else logging.INFO
    logger.log(level, "request", extra={"extra_fields": {
        "request_id": request_id, "method": request.method, "path": request.url.path,
        "status": response.status_code, "ms": elapsed_ms}})
    return response
