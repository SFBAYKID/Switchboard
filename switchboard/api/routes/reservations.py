"""Reservations capability endpoints (the first integration), mock-first.

Concrete, capability-shaped routes (review #1) backing `/v1/reservations/*`. Each
endpoint does the same disciplined sequence:

  1. Token gate (require_bearer_token) — 401 envelope on a bad/missing token.
  2. Validate the typed request body (FastAPI/Pydantic) — 400 envelope on bad input.
  3. Resolve the per-tenant credential — fail CLOSED (404) on an unknown tenant.
  4. Compute the effective deadline = min(per-endpoint budget, caller X-Deadline-Ms)
     minus the safety margin (review #4).
  5. Dispatch to the configured backend under that deadline (review #3-#4): on a
     definitive success return the typed result; otherwise a normalized outcome was
     raised and the exception handler renders it.
  6. Wrap the success in the uniform envelope, carrying the normalized `state`,
     measured `latency_ms`, the `mock` flag, and the correlation `request_id`.

`X-Deadline-Ms` (optional, >=1) is the caller's hard deadline in milliseconds.
`X-Request-ID` (optional) threads correlation; it is echoed on the response.

All four are tagged `source="reservations"`, and `mock` reflects the active backend.
The OpenTable real backend is a seam (Rule 2); flipping `RESERVATIONS_BACKEND` to
`opentable` changes only `mock` (true->false) for the caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from starlette.requests import Request

from switchboard.api.auth import require_bearer_token
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

# The caller's optional hard deadline (ms). Shared declaration so every endpoint
# documents it identically in the OpenAPI spec.
DeadlineHeader = Header(
    default=None,
    alias="X-Deadline-Ms",
    ge=1,
    description="Caller's hard deadline in milliseconds. The effective deadline is "
    "min(this, the per-endpoint budget). On exceed, the endpoint returns state=timeout.",
)


@router.post(
    "/availability",
    response_model=Envelope[AvailabilityResult],
    summary="Reservation Availability v1 (real-time)",
)
async def availability(
    req: AvailabilityRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[AvailabilityResult]:
    """Check reservation availability (real-time; deadline-budgeted)."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.tenant, source=SOURCE, mock=mock)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.availability_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.availability(req, cred),
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
    summary="Reservation Booking v1 (consequential write)",
)
async def book(
    req: BookingRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[BookingResult]:
    """Create a booking (consequential write; idempotent; race-safe — review #5).

    Returns `ok=true` ONLY on an actual confirmation. A slot-gone race surfaces as
    `unavailable`, an ambiguous result as `requires_human` — never a false success.
    """

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.tenant, source=SOURCE, mock=mock)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.book(req, cred),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
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
    summary="Modify a reservation (consequential write)",
)
async def modify(
    req: ModifyRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[ModifyResult]:
    """Modify an existing booking (consequential write; idempotent)."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.tenant, source=SOURCE, mock=mock)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.modify(req, cred),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
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
    summary="Cancel a reservation (consequential write)",
)
async def cancel(
    req: CancelRequest,
    request: Request,
    x_deadline_ms: int | None = DeadlineHeader,
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_bearer_token),
) -> Envelope[CancelResult]:
    """Cancel an existing booking (consequential write; idempotent)."""

    mock = is_mock(settings)
    cred = resolve_credential(CREDENTIAL_NAMESPACE, req.tenant, source=SOURCE, mock=mock)
    backend = select_backend(settings)
    timeout_ms = compute_effective_timeout_ms(
        budget_ms=settings.booking_budget_ms,
        caller_deadline_ms=x_deadline_ms,
        margin_ms=settings.budget_safety_margin_ms,
    )
    result = await call_with_budget(
        backend.cancel(req, cred),
        timeout_ms=timeout_ms,
        source=SOURCE,
        mock=mock,
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
