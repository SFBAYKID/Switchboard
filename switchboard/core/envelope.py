"""Switchboard's uniform response envelope.

EVERY response from Switchboard — success or failure, mock or real, any
integration — has the same top-level shape (architecture.md "uniform response
envelope"), extended per the architecture review:

    { ok, state, data, error, source, latency_ms, mock, request_id }

A caller writes ONE response handler that works across every integration and across
the mock->real swap:
  - `ok`         — true only for a DEFINITIVE, trustworthy answer the caller can act
                   on directly (availability answered; booking confirmed). False for
                   any non-definitive outcome, so a partial failure can never read as
                   false confidence (review #3).
  - `state`      — the NORMALIZED result state for real-time capability endpoints
                   (review #2): exactly one of
                   available | unavailable | confirmed | unknown | timeout |
                   auth_error | rate_limited | requires_human. The single field the
                   calling agent switches on to decide its fallback (review #3).
                   `null` on non-capability endpoints (health, version info).
  - `data`       — the integration payload on success; `null` otherwise.
  - `error`      — structured error on failure; `null` on success. Caller degrades on
                   `error.code`/`retryable`, never by string-matching `message`.
  - `source`     — which module/backend answered (e.g. "reservations", "gateway").
  - `latency_ms` — measured time Switchboard spent (mostly the upstream round trip).
  - `mock`       — true only when a mock backend served this response.
  - `request_id` — correlation id threading the caller's and gateway's logs (review
                   #6). Echoed in the `X-Request-ID` response header too.

`Envelope[T]` is generic over the success `data` type so each endpoint documents its
precise payload shape in the OpenAPI spec (Rule 12). The error path is serialized
with `error_envelope_dict()` — an identical-shaped plain dict used by the exception
handlers (which return `JSONResponse` directly, bypassing `response_model`). Tests
assert success and error envelopes are shape-identical so the invariant holds on
every path.
"""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

# `data`'s concrete type varies per endpoint (AvailabilityResult, BookingResult, …).
T = TypeVar("T")

# The gateway's full normalized result-state vocabulary (review #2/#3). Enumerated in
# the contract (not a bare string) so callers can branch on a closed set. Definitive
# successes: available/unavailable/confirmed/modified/cancelled. Non-definitive
# outcomes: timeout/auth_error/rate_limited/unknown/requires_human. `null` on
# non-capability endpoints (health, version info).
NormalizedState = Literal[
    "available",
    "unavailable",
    "confirmed",
    "modified",
    "cancelled",
    "timeout",
    "auth_error",
    "rate_limited",
    "unknown",
    "requires_human",
]


class ErrorInfo(BaseModel):
    """The structured `error` object (present only when `ok` is false)."""

    code: str  # stable contract code, e.g. "timeout"
    message: str  # human-readable, safe-to-surface explanation (no secrets/PII)
    retryable: bool  # caller hint: might the same request succeed if retried?


class Envelope(BaseModel, Generic[T]):
    """The uniform envelope returned on the SUCCESS path (typed `data`).

    Invariants (asserted by tests on every endpoint):
      - ok == true   => data present, error null
      - ok == false  => data null,   error present
      - real-time capability endpoints always set `state`; ok=true => state is a
        definitive success state (available/unavailable/confirmed)
      - mock == true only when a mock backend actually produced this response
      - request_id is always present
    """

    ok: bool
    state: NormalizedState | None = None
    data: T | None = None
    error: ErrorInfo | None = None
    source: str
    latency_ms: int
    mock: bool
    request_id: str


class ErrorEnvelope(BaseModel):
    """The uniform envelope on a FAILURE path, as a concrete (non-generic) model.

    Used to DOCUMENT error responses in the OpenAPI spec (the routes reference it via
    `responses=`), so the published contract tells the truth about 4xx/5xx — not just
    the 200 success shape. It is shape-identical to `Envelope` with `ok=false` and
    `data=null`; the runtime error body is produced by `error_envelope_dict()`.
    """

    ok: Literal[False] = False
    state: NormalizedState | None = None
    data: None = None
    error: ErrorInfo
    source: str
    latency_ms: int
    mock: bool
    request_id: str


def error_envelope_dict(
    *,
    code: str,
    message: str,
    retryable: bool,
    state: str | None,
    source: str,
    latency_ms: int,
    mock: bool,
    request_id: str,
) -> dict[str, object]:
    """Build the error-path envelope as a plain dict.

    Used by the exception handlers, which must return a `JSONResponse` with an
    explicit status code (so they cannot go through FastAPI's `response_model`). The
    shape is intentionally identical to `Envelope` with `ok=false`, `data=null`, and
    a populated `error` — verified by tests.
    """

    return {
        "ok": False,
        "state": state,
        "data": None,
        "error": {"code": code, "message": message, "retryable": retryable},
        "source": source,
        "latency_ms": latency_ms,
        "mock": mock,
        "request_id": request_id,
    }
