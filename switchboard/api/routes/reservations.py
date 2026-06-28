"""Reservations capability endpoints (the first integration), mock-first.

Concrete, capability-shaped routes (review #1) backing `/v1/reservations/*`. Each
endpoint does the same disciplined sequence:

  1. Token gate (require_bearer_token) — 401 envelope on a bad/missing token.
  2. Validate the typed request body (FastAPI/Pydantic) — 400 envelope on bad input.
  3. Resolve the restaurant's credential by `restaurant_id` — fail CLOSED (404) on an
     unknown restaurant. (A resolution failure is gateway-level: source="gateway".)
  4. Compute the effective deadline = min(per-endpoint budget, caller X-Deadline-Ms)
     minus the safety margin (review #4), and PROPAGATE it into the backend call.
  5. Dispatch to the configured backend under that deadline. WRITES require the
     `Idempotency-Key` header (review #5) and are dispatched with `is_write=True`, so a
     write that times out becomes `requires_human` (ambiguous), never a retryable
     `timeout`.
  6. Wrap the success in the uniform envelope (normalized `state`, measured
     `latency_ms`, `mock`, correlation `request_id`).

Headers:
  - `Authorization: Bearer <token>`  (required) — Switchboard's internal token.
  - `X-Deadline-Ms: <int>`           (optional) — caller's hard deadline, ms.
  - `X-Request-ID: <id>`             (optional) — correlation id, echoed back.
  - `Idempotency-Key: <id>`          (required on book/modify/cancel) — de-dupes retries.

The OpenTable real backend is a seam (Rule 2); flipping `RESERVATIONS_BACKEND` to
`opentable` changes only `mock` (true->false) for the caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from starlette.requests import Request

from switchboard.api.auth import require_bearer_token
from switchboard.api.openapi_responses import (
    COMMON_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from switchboard.api.timing import elapsed_ms, get_request_id
from switchboard.core.config import Settings, get_settings
from switchboard.core.credentials import resolve_credential
from switchboard.core.dispatch import call_with_budget, compute_effective_timeout_ms
from switchboard.core.envelope import Envelope
from switchboard.integrations.reservations import CREDENTIAL_NAMESPACE, SOURCE
from switchboard.integrations.reservations.backends import is_mock, select_backend
from switchboard.integrations.reservations.models import (
    AvailabilityRequest,
    AvailabilityResult,
    BookingRequest,
    BookingResult,
    CancelRequest,
    CancelResult,
    ModifyRequest,
    ModifyResult,
)

router = APIRouter(prefix="/v1/reservations", tags=["reservations"])

# The caller's optional hard deadline (ms). Shared so every endpoint documents it
# identically in the OpenAPI spec.
DeadlineHeader = Header(
    default=None,
    alias="X-Deadline-Ms",
    ge=1,
    description=(
        "Caller's hard deadline in milliseconds. The effective deadline is "
        "min(this, the per-endpoint budget), minus a small safety margin. On exceed, "
        "a read returns state=timeout and a write returns state=requires_human. A "
        "deadline at/below the safety margin (~50ms) will almost always time out."
    ),
)

# The REQUIRED idempotency key for writes (review #5). Generate one per booking intent
# and REUSE it on every retry of that same action so a retry can't double-book.
IdempotencyHeader = Header(
    alias="Idempotency-Key",
    min_length=1,
    max_length=200,
    description="Required on writes. A stable key per logical write; reuse on retry.",
)


@router.post(
    "/availability",
    response_model=Envelope[AvailabilityResult],
    responses=COMMON_ERROR_RESPONSES,
    summary="Reservation Availability v1 (real-time)",
)
async def availability(
    req: AvailabilityRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[AvailabilityResult]:
    """Check whether the requested restaurant/date/time/party is available."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.restaurant_id)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.availability_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.availability(req, cred, timeout_ms),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
    )
    return Envelope[AvailabilityResult](
        ok=True,
        state=result.state,
        data=result,
        error=None,
        source=SOURCE,
        latency_ms=elapsed_ms(request),
        mock=mock,
        request_id=get_request_id(request),
    )


@router.post(
    "/book",
    response_model=Envelope[BookingResult],
    responses=WRITE_ERROR_RESPONSES,
    summary="Reservation Booking v1 (consequential write)",
)
async def book(
    req: BookingRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    idempotency_key: str = IdempotencyHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[BookingResult]:
    """Book the reservation (consequential write; idempotent; race-safe — review #5).

    Returns `ok=true` ONLY on an actual confirmation. A slot-gone race surfaces as
    `unavailable`, an ambiguous result (incl. a write timeout) as `requires_human` —
    never a false success.
    """

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.restaurant_id)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.book(req, cred, timeout_ms, idempotency_key),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
        is_write=True,
    )
    return Envelope[BookingResult](
        ok=True,
        state=result.state,
        data=result,
        error=None,
        source=SOURCE,
        latency_ms=elapsed_ms(request),
        mock=mock,
        request_id=get_request_id(request),
    )


@router.post(
    "/modify",
    response_model=Envelope[ModifyResult],
    responses=WRITE_ERROR_RESPONSES,
    summary="Modify a reservation (consequential write)",
)
async def modify(
    req: ModifyRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    idempotency_key: str = IdempotencyHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[ModifyResult]:
    """Modify an existing booking (consequential write; idempotent)."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.restaurant_id)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.modify(req, cred, timeout_ms, idempotency_key),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
        is_write=True,
    )
    return Envelope[ModifyResult](
        ok=True,
        state=result.state,
        data=result,
        error=None,
        source=SOURCE,
        latency_ms=elapsed_ms(request),
        mock=mock,
        request_id=get_request_id(request),
    )


@router.post(
    "/cancel",
    response_model=Envelope[CancelResult],
    responses=WRITE_ERROR_RESPONSES,
    summary="Cancel a reservation (consequential write)",
)
async def cancel(
    req: CancelRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    idempotency_key: str = IdempotencyHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[CancelResult]:
    """Cancel an existing booking (consequential write; idempotent)."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.restaurant_id)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.cancel(req, cred, timeout_ms, idempotency_key),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
        is_write=True,
    )
    return Envelope[CancelResult](
        ok=True,
        state=result.state,
        data=result,
        error=None,
        source=SOURCE,
        latency_ms=elapsed_ms(request),
        mock=mock,
        request_id=get_request_id(request),
    )
