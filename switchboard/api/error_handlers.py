"""Exception handlers that render the uniform error envelope on EVERY failure path.

Switchboard guarantees a caller NEVER sees a raw stack trace, a leaked vendor error,
or FastAPI's default `{"detail": …}` shape — only the uniform envelope (architecture.md;
QA: "a leaked 500/stack trace instead of the uniform error envelope" is a do-not-ship
bug). Three handlers cover every failure:

  - `AppError`              -> the mapped envelope (status, code, retryable, state).
  - `RequestValidationError`-> a `bad_request` (400) envelope. The detail is a
                               sanitized list of field locations ONLY — never the
                               offending input values (which could echo secrets/PII).
  - `Exception` (catch-all) -> a generic `internal_error` (500) envelope; the full
                               traceback is logged server-side, never sent to the
                               caller.

Each handler reads the correlation id + measured latency off `request.state` so the
error envelope carries the same `request_id`/`latency_ms` as a success would.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from switchboard.api.timing import REQUEST_ID_HEADER, elapsed_ms, get_request_id
from switchboard.core.envelope import error_envelope_dict
from switchboard.core.errors import AppError, BadRequestError, InternalError

logger = logging.getLogger("switchboard.errors")


def _render(request: Request, exc: AppError, status_code: int) -> JSONResponse:
    """Serialize an `AppError` into the uniform error envelope `JSONResponse`."""

    request_id = get_request_id(request)
    body = error_envelope_dict(
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        state=exc.state,
        source=exc.source,
        latency_ms=elapsed_ms(request),
        mock=exc.mock,
        request_id=request_id,
    )
    response = JSONResponse(status_code=status_code, content=body)
    # Echo the correlation id here too (F3): the 500 catch-all runs in
    # ServerErrorMiddleware, OUTSIDE the timing middleware, so its post-step that
    # normally sets this header is skipped. Setting it here guarantees the header is
    # present on EVERY error response, including the internal-error net.
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render any `AppError` as its mapped uniform error envelope."""

    # Starlette types handlers as (Request, Exception); we only register this for
    # AppError, so the isinstance is a safe narrowing for the type checker.
    assert isinstance(exc, AppError)
    return _render(request, exc, exc.http_status)


async def validation_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Render a request-validation failure as a `bad_request` envelope (400).

    The message lists the failing field LOCATIONS only (e.g. "body.party_size"),
    never the submitted values — a validation error must not echo potentially
    sensitive input back to the caller or into logs.
    """

    assert isinstance(exc, RequestValidationError)
    locations = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        if loc:
            locations.append(loc)
    detail = ", ".join(locations) if locations else "request body"
    mapped = BadRequestError(f"Request validation failed for: {detail}")
    return _render(request, mapped, mapped.http_status)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort net: render any unexpected exception as `internal_error` (500).

    The full traceback is logged server-side (no secrets in the log message itself);
    the caller receives only the generic, safe envelope — never a stack trace.
    """

    logger.exception(
        "unhandled exception request_id=%s path=%s",
        get_request_id(request),
        request.url.path,
    )
    mapped = InternalError()
    return _render(request, mapped, mapped.http_status)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all three handlers onto the app (call from the app factory)."""

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
