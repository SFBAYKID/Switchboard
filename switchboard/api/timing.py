"""Request timing + correlation-id middleware (review #6, Rule 5).

Two cross-cutting concerns live here:

1. **Correlation id (review #6).** One `request_id` threads the caller's logs, the
   gateway's logs, and the response. It is taken from the inbound `X-Request-ID`
   header when the caller supplies one (so a caller's id flows through), else a fresh
   one is generated. It is stored on `request.state`, echoed in the `X-Request-ID`
   response header, included in the uniform envelope, and logged on completion.

2. **Honest latency measurement (Rule 5).** The middleware stamps a high-resolution
   start time on `request.state`; routes and exception handlers read it to populate
   the envelope's `latency_ms`. This is MEASURED, not guessed — the real cost is the
   upstream round trip, and `latency_ms` exists so that is observed, not assumed.

Logging is deliberately minimal and secret-free (Rule 7 / guardian doc): method,
path, status, latency, mock flag, request id — never tokens, credentials, or bodies.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("switchboard.request")

# The correlation-id header (both inbound and on the response).
REQUEST_ID_HEADER: str = "X-Request-ID"

# A caller-supplied request id must be a sane, bounded token to be trusted (avoid
# log injection / absurd values). Otherwise we generate our own.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def _new_request_id() -> str:
    """Generate a fresh correlation id."""

    return uuid.uuid4().hex


def _resolve_inbound_request_id(request: Request) -> str:
    """Use the caller's X-Request-ID if it is safe, else generate one."""

    inbound = request.headers.get(REQUEST_ID_HEADER)
    if inbound and _SAFE_REQUEST_ID.match(inbound):
        return inbound
    return _new_request_id()


def get_request_id(request: Request) -> str:
    """Return the correlation id for this request (set by the middleware)."""

    rid = getattr(request.state, "request_id", None)
    # Defensive: if the middleware somehow didn't run, mint one rather than crash.
    return rid if isinstance(rid, str) else _new_request_id()


def elapsed_ms(request: Request) -> int:
    """Return ms elapsed since the request started (set by the middleware)."""

    start = getattr(request.state, "start_perf", None)
    if not isinstance(start, float):
        return 0
    return max(0, int((time.perf_counter() - start) * 1000))


async def timing_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Stamp start time + correlation id, then log a minimal, secret-free record."""

    request.state.start_perf = time.perf_counter()
    request.state.request_id = _resolve_inbound_request_id(request)

    response = await call_next(request)

    # Echo the correlation id so the caller can tie its logs to the gateway's.
    response.headers[REQUEST_ID_HEADER] = request.state.request_id

    # Minimal, secret-free completion log (no tokens, credentials, or bodies).
    logger.info(
        "request_id=%s method=%s path=%s status=%s latency_ms=%s",
        request.state.request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms(request),
    )
    return response
