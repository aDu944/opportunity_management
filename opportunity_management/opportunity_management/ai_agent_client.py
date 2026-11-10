"""
The one module that talks to the Claude API (`anthropic`, imported lazily so
the rest of the app and every test import without the package).

    call(request, api_key, model, effort, max_tokens)
        → {"stop_reason", "text", "tool_uses": [{id, name, input}], "content",
           "usage": {input_tokens, output_tokens, cache_read_tokens,
           cache_write_tokens}, "model", "latency_ms", "error"}

One API call per `call`; the tool round trips are ai_agent_pure.converse.
Never raises for API failures (typed SDK errors become `error`), never logs
the request body or the key. `content` is the assistant content exactly as
returned, to echo back on a tool round trip (thinking blocks included).
"""

import time

FALLBACK_BETA = "server-side-fallback-2026-07-01"
TIMEOUT_SECONDS = 30  # x (1 + MAX_RETRIES) x 3 calls stays inside the short queue's 300 s
MAX_RETRIES = 1


def _usage(response):
    """Our usage names, summed over every attempt (`usage.iterations`) when a
    refusal fallback ran; else the top-level usage."""
    usage = getattr(response, "usage", None)
    parts = [i for i in (getattr(usage, "iterations", None) or [])] or ([usage] if usage else [])
    out = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    for part in parts:
        out["input_tokens"] += int(getattr(part, "input_tokens", 0) or 0)
        out["output_tokens"] += int(getattr(part, "output_tokens", 0) or 0)
        out["cache_read_tokens"] += int(getattr(part, "cache_read_input_tokens", 0) or 0)
        out["cache_write_tokens"] += int(getattr(part, "cache_creation_input_tokens", 0) or 0)
    return out


def _error(kind, exc):
    status = getattr(exc, "status_code", None)
    message = str(getattr(exc, "message", "") or exc.__class__.__name__)[:300]
    return "{0}{1}: {2}".format(kind, " ({0})".format(status) if status else "", message)


def call(request, api_key, model, effort, max_tokens):
    started = time.monotonic()
    out = {"stop_reason": None, "text": "", "tool_uses": [], "content": [], "usage": {},
           "model": model, "latency_ms": 0, "error": None}
    if not api_key:
        out["error"] = "no API key (site_config anthropic_api_key)"
        return out
    try:
        import anthropic
    except ImportError:
        out["error"] = "the anthropic package is not installed"
        return out

    params = {k: v for k, v in (request or {}).items() if k in ("system", "tools", "messages")}
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES)
        response = client.beta.messages.create(
            model=model,
            max_tokens=int(max_tokens),
            output_config={"effort": effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **params,
        )
    except anthropic.BadRequestError as e:          # 400 — our request is wrong; do not retry
        out["error"] = _error("bad request", e)
    except anthropic.AuthenticationError as e:      # 401 — key wrong or revoked
        out["error"] = _error("authentication", e)
    except anthropic.PermissionDeniedError as e:    # 403
        out["error"] = _error("permission denied", e)
    except anthropic.NotFoundError as e:            # 404 — bad model id
        out["error"] = _error("not found", e)
    except anthropic.RateLimitError as e:           # 429 — after the SDK's own retries
        out["error"] = _error("rate limited", e)
    except anthropic.APIStatusError as e:           # any other non-2xx (5xx, 529 overloaded)
        out["error"] = _error("api status", e)
    except anthropic.APITimeoutError as e:          # before APIConnectionError (its subclass)
        out["error"] = _error("timeout", e)
    except anthropic.APIConnectionError as e:       # network failure, no response
        out["error"] = _error("connection", e)
    else:
        # stop_reason first: a refusal has empty (or partial) content.
        out["stop_reason"] = response.stop_reason
        out["model"] = getattr(response, "model", None) or model
        out["usage"] = _usage(response)
        if response.stop_reason != "refusal":
            out["content"] = list(response.content)
            out["text"] = "".join(b.text for b in response.content if b.type == "text").strip()
            out["tool_uses"] = [{"id": b.id, "name": b.name, "input": dict(b.input or {})}
                                for b in response.content if b.type == "tool_use"]
    out["latency_ms"] = int((time.monotonic() - started) * 1000)
    return out
