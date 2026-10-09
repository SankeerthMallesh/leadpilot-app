"""LLM wrapper with two interchangeable backends: Anthropic (default) and Ollama (local / self-hosted).

Features: structured output (forced tool-use on Anthropic, JSON-schema `format` on Ollama), prompt caching,
streaming, timeouts, retry with backoff + jitter, a token-bucket rate limit, a concurrency gate for Ollama,
model warm-up, health checks, and cost tracking. The browser never talks to either backend directly.
"""
import json
import logging
import random
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger("leadpilot.llm")

CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


class LLMError(Exception):
    """Any LLM failure."""


class LLMNotConfigured(LLMError):
    """ANTHROPIC_API_KEY is missing."""


@dataclass
class LLMResult:
    """A completed (non-streaming) model call."""

    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    tool_input: dict | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class StreamUsage:
    """Usage reported at the end of a streamed call."""

    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    first_token_ms: float = 0.0
    tokens_per_second: float = 0.0


class TokenBucket:
    """Simple in-process token bucket (a Redis-backed limiter arrives with the job queue)."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.tokens = float(per_minute)
        self.rate = per_minute / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


_bucket: TokenBucket | None = None
_http_client: httpx.Client | None = None
_http_lock = threading.Lock()


def _http() -> httpx.Client:
    """One pooled keep-alive client for all calls (skips a TLS handshake on every request)."""
    global _http_client
    with _http_lock:
        if _http_client is None:
            _http_client = httpx.Client(limits=httpx.Limits(max_keepalive_connections=10, max_connections=20))
        return _http_client


def _get_bucket() -> TokenBucket:
    global _bucket
    if _bucket is None:
        _bucket = TokenBucket(get_settings().llm_rate_per_minute)
    return _bucket


def compute_cost(model: str, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """Estimate USD cost from env-configured per-million-token prices (cache-aware)."""
    s = get_settings()
    if model in _ollama_models():
        return 0.0  # local models have no per-token fee
    if model == s.claude_model_fast:
        p_in, p_out = s.price_fast_in_per_mtok, s.price_fast_out_per_mtok
    else:
        p_in, p_out = s.price_main_in_per_mtok, s.price_main_out_per_mtok
    total_in = tokens_in + cache_read * CACHE_READ_FACTOR + cache_write * CACHE_WRITE_FACTOR
    return (total_in * p_in + tokens_out * p_out) / 1_000_000


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of model text (tolerates code fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("Model response contained no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("Model JSON was not an object")
    return data


def tool_for(name: str, description: str, model_cls: type[BaseModel]) -> dict:
    """Build an Anthropic tool definition from a Pydantic model (with $refs inlined)."""
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):  # noqa: ANN001, ANN202
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs[node["$ref"].split("/")[-1]]
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **extra})
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return {"name": name, "description": description, "input_schema": resolve(schema)}


def _headers() -> dict[str, str]:
    s = get_settings()
    if not s.anthropic_api_key:
        raise LLMNotConfigured("ANTHROPIC_API_KEY is not set")
    return {"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01",
            "content-type": "application/json"}


def _system(system: str, cache: bool):  # noqa: ANN202
    """Mark the (stable) system prompt cacheable so repeat calls are faster and cheaper."""
    if not cache:
        return system
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _backoff(attempt: int) -> None:
    time.sleep(min(30.0, 2**attempt + random.random()))


def _parse(data: dict, model: str) -> LLMResult:
    content = data.get("content", [])
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    tool_input = next((b.get("input") for b in content if b.get("type") == "tool_use"), None)
    usage = data.get("usage", {})
    t_in, t_out = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    c_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    c_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    return LLMResult(text, t_in, t_out, compute_cost(model, t_in, t_out, c_read, c_write), model,
                     tool_input if isinstance(tool_input, dict) else None, c_read, c_write)


def complete(
    *, system: str, messages: list[dict], model: str | None = None, max_tokens: int = 2000,
    tool: dict | None = None, cache_system: bool = True, provider: str | None = None,
) -> LLMResult:
    """Call the model with retries. With `tool`, the reply is validated structured output."""
    if resolve_provider(provider) == "ollama":
        return _ollama_complete(system, messages, model, max_tokens, tool)
    s = get_settings()
    headers = _headers()
    model = model or s.claude_model_main
    body: dict = {"model": model, "max_tokens": max_tokens, "system": _system(system, cache_system),
                  "messages": messages}
    if tool:
        body["tools"] = [tool]
        body["tool_choice"] = {"type": "tool", "name": tool["name"]}
    last_error = "unknown error"
    for attempt in range(s.llm_max_retries):
        _get_bucket().acquire()
        try:
            resp = _http().post(f"{s.anthropic_base_url}/v1/messages", json=body, headers=headers,
                                timeout=s.llm_timeout_seconds)
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc.__class__.__name__}"
        else:
            if resp.status_code == 200:
                return _parse(resp.json(), model)
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code not in (408, 409, 429) and resp.status_code < 500:
                raise LLMError(f"Anthropic API rejected the request ({last_error})")
        if attempt < s.llm_max_retries - 1:
            _backoff(attempt)
    raise LLMError(f"Anthropic API failed after retries ({last_error})")


def stream(
    *, system: str, messages: list[dict], model: str | None = None, max_tokens: int = 1500,
    cache_system: bool = True, provider: str | None = None,
) -> Iterator[tuple[str, str | StreamUsage]]:
    """Stream a reply. Yields ("delta", text) chunks, then ("usage", StreamUsage).

    Retries only before the first byte; once tokens flow, failures raise LLMError.
    """
    if resolve_provider(provider) == "ollama":
        yield from _ollama_stream(system, messages, model, max_tokens)
        return
    s = get_settings()
    headers = _headers()
    model = model or s.claude_model_main
    body = {"model": model, "max_tokens": max_tokens, "system": _system(system, cache_system),
            "messages": messages, "stream": True}
    last_error = "unknown error"
    started = False
    for attempt in range(s.llm_max_retries):
        _get_bucket().acquire()
        try:
            with _http().stream("POST", f"{s.anthropic_base_url}/v1/messages", json=body, headers=headers,
                                timeout=s.llm_timeout_seconds) as resp:
                if resp.status_code != 200:
                    resp.read()
                    last_error = f"HTTP {resp.status_code}"
                    if resp.status_code not in (408, 409, 429) and resp.status_code < 500:
                        raise LLMError(f"Anthropic API rejected the request ({last_error})")
                else:
                    for item in _read_stream(resp, model):
                        started = True
                        yield item
                    return
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc.__class__.__name__}"
            if started:  # never retry after tokens were sent: the reply would be duplicated
                raise LLMError("The connection to the model was interrupted.") from exc
        if attempt < s.llm_max_retries - 1:
            _backoff(attempt)
    raise LLMError(f"Anthropic API failed after retries ({last_error})")


def _read_stream(resp: httpx.Response, model: str) -> Iterator[tuple[str, str | StreamUsage]]:
    t_in = t_out = c_read = c_write = 0
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        try:
            event = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
            yield "delta", event["delta"].get("text", "")
        elif kind == "message_start":
            u = event.get("message", {}).get("usage", {})
            t_in = int(u.get("input_tokens", 0))
            c_read = int(u.get("cache_read_input_tokens", 0) or 0)
            c_write = int(u.get("cache_creation_input_tokens", 0) or 0)
        elif kind == "message_delta":
            t_out = int(event.get("usage", {}).get("output_tokens", t_out))
        elif kind == "error":
            raise LLMError("Model stream error: " + str(event.get("error", {}).get("message", "unknown")))
    yield "usage", StreamUsage(t_in, t_out, compute_cost(model, t_in, t_out, c_read, c_write), model,
                               c_read, c_write)


# ======================================================================================
# Provider selection
# ======================================================================================
def resolve_provider(provider: str | None = None) -> str:
    """Return "anthropic" or "ollama" (explicit value, else LLM_PROVIDER)."""
    value = (provider or get_settings().llm_provider or "anthropic").strip().lower()
    return "ollama" if value == "ollama" else "anthropic"


def active_provider() -> str:
    """Provider name for cost logging and the System page."""
    return resolve_provider(None)


def not_configured_hint(provider: str | None = None) -> str:
    """Friendly 'what to do' text for LLMNotConfigured."""
    if resolve_provider(provider) == "ollama":
        return "Set OLLAMA_BASE_URL and OLLAMA_MODEL in your .env file and make sure Ollama is running."
    return "Add ANTHROPIC_API_KEY to your .env file and restart."


# ======================================================================================
# Ollama backend (/api/chat). Docs: https://github.com/ollama/ollama/blob/main/docs/api.md
# ======================================================================================
_ollama_gate: threading.BoundedSemaphore | None = None
_gate_lock = threading.Lock()


def _ollama_models() -> set[str]:
    s = get_settings()
    return {m for m in (s.ollama_model, s.ollama_fast_model) if m}


def _ollama_model(model: str | None) -> str:
    """Map the app's Claude model names to the configured Ollama models; pass real tags through."""
    s = get_settings()
    if not model or model == s.claude_model_main:
        return s.ollama_model
    if model == s.claude_model_fast:
        return s.ollama_fast_model or s.ollama_model
    return model


def _gate() -> threading.BoundedSemaphore:
    global _ollama_gate
    with _gate_lock:
        if _ollama_gate is None:
            _ollama_gate = threading.BoundedSemaphore(max(1, get_settings().ollama_max_concurrency))
        return _ollama_gate


def _ollama_timeout() -> httpx.Timeout:
    s = get_settings()
    return httpx.Timeout(s.ollama_timeout_seconds, connect=s.ollama_connect_timeout_seconds)


def _ollama_headers() -> dict[str, str]:
    s = get_settings()
    if not s.ollama_base_url:
        raise LLMNotConfigured("OLLAMA_BASE_URL is not set")
    headers = {"content-type": "application/json"}
    if s.ollama_api_key:
        headers["authorization"] = f"Bearer {s.ollama_api_key}"
    return headers


def _ollama_options(max_tokens: int, structured: bool) -> dict[str, Any]:
    s = get_settings()
    opts: dict[str, Any] = {
        "num_ctx": s.ollama_num_ctx, "num_predict": max_tokens,
        "temperature": s.ollama_structured_temperature if structured else s.ollama_temperature,
        "top_p": s.ollama_top_p, "repeat_penalty": s.ollama_repeat_penalty,
    }
    if s.ollama_num_gpu is not None:
        opts["num_gpu"] = s.ollama_num_gpu
    if s.ollama_num_thread is not None:
        opts["num_thread"] = s.ollama_num_thread
    return opts


def _ollama_body(system: str, messages: list[dict], model: str, max_tokens: int, stream_on: bool,
                 tool: dict | None = None) -> dict[str, Any]:
    s = get_settings()
    sys_text = system
    if tool:
        sys_text += ("\n\nReply with ONE JSON object only (no prose, no code fences) that matches this "
                     "JSON schema:\n" + json.dumps(tool["input_schema"], separators=(",", ":")))
    body: dict[str, Any] = {
        "model": model, "stream": stream_on, "keep_alive": _keep_alive(s.ollama_keep_alive),
        "messages": [{"role": "system", "content": sys_text}, *messages],
        "options": _ollama_options(max_tokens, structured=tool is not None),
    }
    if tool:
        body["format"] = tool["input_schema"]  # structured outputs: constrains the reply to the schema
    return body


def _keep_alive(value: str) -> str | int:
    """Ollama accepts a duration string ("30m") or a number of seconds (-1 = keep loaded forever)."""
    try:
        return int(value)
    except ValueError:
        return value


def _ollama_error(resp: httpx.Response, model: str) -> LLMError:
    """Turn an Ollama error response into a message an operator can act on."""
    try:
        detail = str(resp.json().get("error", ""))
    except (ValueError, AttributeError):
        detail = ""
    low = detail.lower()
    if resp.status_code == 404 or "not found" in low:
        return LLMError(f"Model '{model}' is not installed on the Ollama server. Run: ollama pull {model}")
    if "memory" in low:
        return LLMError(f"Not enough memory to load '{model}'. Use a smaller model or a lower OLLAMA_NUM_CTX.")
    if resp.status_code in (401, 403):
        return LLMError("Ollama rejected the request (check OLLAMA_API_KEY / proxy token).")
    return LLMError(f"Ollama error (HTTP {resp.status_code}){': ' + detail[:200] if detail else ''}")


def _retryable(status: int) -> bool:
    return status in (408, 409, 429, 502, 503, 504) or status >= 500


def _unreachable(exc: Exception) -> str:
    base = get_settings().ollama_base_url
    if isinstance(exc, httpx.TimeoutException):
        return f"Ollama at {base} timed out (the model may still be loading)."
    return f"Cannot reach Ollama at {base}. Is it running (ollama serve)?"


class _Slot:
    """Context manager: wait in line for an Ollama generation slot (protects the model from overload)."""

    def __enter__(self) -> "_Slot":
        if not _gate().acquire(timeout=get_settings().ollama_queue_timeout_seconds):
            raise LLMError("The AI is busy with other requests. Please try again in a moment.")
        return self

    def __exit__(self, *exc: object) -> None:
        _gate().release()


def _ollama_usage(final: dict, model: str, first_token_ms: float) -> StreamUsage:
    t_in, t_out = int(final.get("prompt_eval_count", 0) or 0), int(final.get("eval_count", 0) or 0)
    eval_ns = int(final.get("eval_duration", 0) or 0)
    tps = round(t_out / (eval_ns / 1e9), 1) if eval_ns else 0.0
    logger.info("ollama_done", extra={"extra_fields": {
        "model": model, "prompt_tokens": t_in, "output_tokens": t_out, "first_token_ms": round(first_token_ms),
        "tokens_per_second": tps, "load_ms": round(int(final.get("load_duration", 0) or 0) / 1e6)}})
    return StreamUsage(t_in, t_out, 0.0, model, 0, 0, round(first_token_ms), tps)


def _read_ollama_stream(lines: Iterator[str], model: str, t0: float) -> Iterator[tuple[str, str | StreamUsage]]:
    """Parse Ollama's NDJSON stream (one JSON object per line; httpx reassembles split chunks)."""
    first_ms = 0.0
    final: dict | None = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("error"):
            raise LLMError("Model stream error: " + str(event["error"])[:200])
        piece = (event.get("message") or {}).get("content", "")
        if piece:
            if not first_ms:
                first_ms = (time.monotonic() - t0) * 1000
            yield "delta", piece
        if event.get("done"):
            final = event
            break
    if final is None:
        raise LLMError("The connection to the model was interrupted.")
    yield "usage", _ollama_usage(final, model, first_ms)


def _ollama_stream(system: str, messages: list[dict], model: str | None, max_tokens: int
                   ) -> Iterator[tuple[str, str | StreamUsage]]:
    s = get_settings()
    headers = _ollama_headers()
    name = _ollama_model(model)
    body = _ollama_body(system, messages, name, max_tokens, stream_on=True)
    last_error = "unknown error"
    started = False
    with _Slot():
        for attempt in range(s.llm_max_retries):
            t0 = time.monotonic()
            try:
                with _http().stream("POST", f"{s.ollama_base_url}/api/chat", json=body, headers=headers,
                                    timeout=_ollama_timeout()) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        err = _ollama_error(resp, name)
                        if not _retryable(resp.status_code):
                            raise err
                        last_error = str(err)
                    else:
                        for item in _read_ollama_stream(resp.iter_lines(), name, t0):
                            started = True
                            yield item
                        return
            except httpx.HTTPError as exc:
                last_error = _unreachable(exc)
                if started:
                    raise LLMError("The connection to the model was interrupted.") from exc
            if attempt < s.llm_max_retries - 1:
                _backoff(attempt)
    raise LLMError(last_error)


def _ollama_complete(system: str, messages: list[dict], model: str | None, max_tokens: int,
                     tool: dict | None) -> LLMResult:
    s = get_settings()
    headers = _ollama_headers()
    name = _ollama_model(model)
    body = _ollama_body(system, messages, name, max_tokens, stream_on=False, tool=tool)
    last_error = "unknown error"
    with _Slot():
        for attempt in range(s.llm_max_retries):
            try:
                resp = _http().post(f"{s.ollama_base_url}/api/chat", json=body, headers=headers,
                                    timeout=_ollama_timeout())
            except httpx.HTTPError as exc:
                last_error = _unreachable(exc)
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    text = (data.get("message") or {}).get("content", "")
                    tool_input = None
                    if tool:
                        try:
                            parsed = json.loads(text)
                            tool_input = parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            tool_input = None  # callers fall back to extract_json / one retry
                    return LLMResult(text, int(data.get("prompt_eval_count", 0) or 0),
                                     int(data.get("eval_count", 0) or 0), 0.0, name, tool_input)
                err = _ollama_error(resp, name)
                if not _retryable(resp.status_code):
                    raise err
                last_error = str(err)
            if attempt < s.llm_max_retries - 1:
                _backoff(attempt)
    raise LLMError(last_error)


def warm_up() -> bool:
    """Load the Ollama model into memory (an empty chat request loads it) so the first real message is fast."""
    s = get_settings()
    try:
        resp = _http().post(f"{s.ollama_base_url}/api/chat", headers=_ollama_headers(), timeout=_ollama_timeout(),
                            json={"model": s.ollama_model, "messages": [], "stream": False,
                                  "keep_alive": _keep_alive(s.ollama_keep_alive)})
        return resp.status_code == 200
    except (httpx.HTTPError, LLMError):
        return False


def ollama_health() -> dict[str, Any]:
    """Quick status for the System page: reachable? version? model installed? model loaded in memory?"""
    s = get_settings()
    out: dict[str, Any] = {"reachable": False, "version": "", "installed": False, "loaded": False, "error": ""}
    try:
        headers = _ollama_headers()
        t = httpx.Timeout(4.0)
        out["version"] = _http().get(f"{s.ollama_base_url}/api/version", headers=headers, timeout=t).json().get("version", "")
        out["reachable"] = True
        tags = _http().get(f"{s.ollama_base_url}/api/tags", headers=headers, timeout=t).json().get("models", [])
        names = {m.get("name", "") for m in tags}
        out["installed"] = s.ollama_model in names or f"{s.ollama_model}:latest" in names
        ps = _http().get(f"{s.ollama_base_url}/api/ps", headers=headers, timeout=t).json().get("models", [])
        out["loaded"] = any(m.get("name", "").startswith(s.ollama_model) for m in ps)
    except (httpx.HTTPError, ValueError, LLMError) as exc:
        out["error"] = str(exc)[:200] or exc.__class__.__name__
    return out
