"""Switchboard structured errors, normalized states + HTTP-status mapping.

Every failure path in Switchboard is an `AppError` subclass. A single FastAPI
exception handler turns ANY `AppError` into the uniform error envelope, so a caller
NEVER sees a raw stack trace, a leaked vendor error, or a per-integration error
dialect (architecture.md "uniform envelope on EVERY response"; review #2 "never leak
a raw vendor error or a false confirmation").

Two CLASSES of error, deliberately distinct (review #2/#3):

1. **Gateway-level faults** — the request never validly entered the capability:
   bad request, bad/missing internal bearer token, unknown tenant (fail closed),
   or an unexpected internal fault. These have NO normalized `state` (`state=None`)
   because no upstream interaction occurred. The caller branches on `error.code`.

2. **Normalized upstream-outcome states** — the request was well-formed and
   authorized, reached (or attempted) the upstream capability, and the outcome is
   normalized to exactly one of the review's vocabulary:
       timeout | auth_error | rate_limited | unknown | requires_human | unavailable
   These carry a `state`, surfaced as the first-class `state` field in the envelope,
   so "the caller owns the fallback" (review #3): the calling agent switches on the
   single normalized `state` and decides what to do. `ok` is false for all of them
   (a non-definitive outcome must never read as success — review #3).

   Note the success states (`available`, `unavailable`-for-availability, `confirmed`)
   are NOT errors — they are returned as result data with `ok=true`. Booking's
   `unavailable` (the slot vanished) IS modeled as an error outcome so a booking
   caller checking `ok` only ever sees true on an actual confirmation (no false
   confidence). See `BookingUnavailableOutcome`.

`source`/`mock` are envelope-tagging metadata carried on the error so the handler
reports WHICH backend produced the failure and whether it was a mock. They default
to gateway-level (source="gateway", mock=False); an integration backend/dispatch
sets them to its own values when it raises an upstream-outcome error.
"""

from __future__ import annotations

from typing import ClassVar

# Source label for faults in the gateway itself, before/around any integration
# backend (auth gate, request validation, the internal-error net).
GATEWAY_SOURCE: str = "gateway"


class AppError(Exception):
    """Base class for every Switchboard error mapped to the error envelope.

    Subclasses set the class-level contract fields: `code` (stable, caller branches
    on it), `http_status`, `retryable`, and `state` (the normalized result state, or
    None for gateway-level faults). Instances carry a safe `message` plus the
    envelope-tagging `source`/`mock`.

    Messages are safe-by-construction: they NEVER contain secrets, credentials, raw
    upstream payloads, or another tenant's identifiers.
    """

    code: ClassVar[str] = "internal_error"
    http_status: ClassVar[int] = 500
    retryable: ClassVar[bool] = False
    # Normalized result state for upstream-outcome errors; None for gateway faults.
    state: ClassVar[str | None] = None

    def __init__(
        self,
        message: str,
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.source: str = source
        self.mock: bool = mock


# ── Class 1: gateway-level faults (no normalized state) ──────────────────────────


class BadRequestError(AppError):
    """The inbound request was malformed or semantically invalid (400)."""

    code = "bad_request"
    http_status = 400
    retryable = False
    state = None

    def __init__(
        self,
        message: str = "The request was invalid.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class UnauthorizedError(AppError):
    """The internal bearer token was missing or invalid (401).

    Generic message — never reveals whether a token exists or hints at its shape.
    This is the INTERNAL caller->gateway hop, distinct from upstream `auth_error`.
    """

    code = "unauthorized"
    http_status = 401
    retryable = False
    state = None

    def __init__(
        self,
        message: str = "Missing or invalid bearer token.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class TenantNotFoundError(AppError):
    """No credentials configured for the requested (tenant, integration) (404).

    The FAIL-CLOSED outcome for an unknown/unconfigured tenant: Switchboard refuses
    rather than falling back to a default tenant's credentials. The message never
    lists which tenants exist (no cross-tenant disclosure). This is a gateway/config
    issue detected before any upstream call, so it has no normalized upstream state.
    """

    code = "not_found"
    http_status = 404
    retryable = False
    state = None

    def __init__(
        self,
        message: str = "No credentials are configured for the requested tenant.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class InternalError(AppError):
    """Last-resort safety net for an unexpected fault (500).

    Ensures a caller still receives the uniform envelope rather than a leaked stack
    trace. Not retryable (a bug won't fix itself on retry).
    """

    code = "internal_error"
    http_status = 500
    retryable = False
    state = None

    def __init__(
        self,
        message: str = "An internal error occurred.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


# ── Class 2: normalized upstream-outcome states (review #2) ──────────────────────


class TimeoutOutcome(AppError):
    """The upstream did not answer within the (deadline-bounded) budget (504).

    Returned promptly, within budget, so the caller degrades gracefully instead of
    hanging (review #3/#4). Retryable: the upstream may simply have been slow.
    """

    code = "timeout"
    http_status = 504
    retryable = True
    state = "timeout"

    def __init__(
        self,
        message: str = "The upstream service did not respond within the deadline.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class AuthErrorOutcome(AppError):
    """The tenant's UPSTREAM credential was rejected by the vendor (502).

    Distinct from the internal `unauthorized` (a bad gateway bearer token). Not
    retryable: the tenant's upstream credential needs fixing, not a retry. The raw
    vendor auth error is never forwarded.
    """

    code = "auth_error"
    http_status = 502
    retryable = False
    state = "auth_error"

    def __init__(
        self,
        message: str = "The upstream rejected the tenant's credentials.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class RateLimitedOutcome(AppError):
    """The upstream rate-limited the request (429). Retryable with backoff."""

    code = "rate_limited"
    http_status = 429
    retryable = True
    state = "rate_limited"

    def __init__(
        self,
        message: str = "The upstream rate-limited the request.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class UnknownOutcome(AppError):
    """The upstream errored or returned unusable/malformed data (502).

    The catch-all normalized state for an upstream interaction we cannot classify
    into a more specific outcome — including malformed/partial responses and
    unexpected upstream faults. The raw detail is NEVER forwarded (it may carry
    secrets/PII); a stable, safe message is returned. Retryable by default.
    """

    code = "unknown"
    http_status = 502
    retryable = True
    state = "unknown"

    def __init__(
        self,
        message: str = "The upstream returned an unexpected or unusable response.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class RequiresHumanOutcome(AppError):
    """The outcome is ambiguous and a human must reconcile it (409).

    The key case (review #5): a write where the upstream may have accepted but the
    confirmation was lost — Switchboard must NOT report a false success. It returns
    `requires_human` so the caller escalates/reconciles. Not retryable automatically
    (a blind retry could double-act).
    """

    code = "requires_human"
    http_status = 409
    retryable = False
    state = "requires_human"

    def __init__(
        self,
        message: str = "The result is ambiguous and requires human reconciliation.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)


class BookingUnavailableOutcome(AppError):
    """A booking failed because the slot was no longer available (409).

    The availability != booked race (review #5): the slot vanished between the
    availability check and the booking. Modeled as an error outcome (ok=false) so a
    booking caller that checks only `ok` never mistakes it for a confirmation. Not
    retryable (the slot is gone; re-check availability for alternatives).
    """

    code = "unavailable"
    http_status = 409
    retryable = False
    state = "unavailable"

    def __init__(
        self,
        message: str = "The requested slot is no longer available.",
        *,
        source: str = GATEWAY_SOURCE,
        mock: bool = False,
    ) -> None:
        super().__init__(message, source=source, mock=mock)
