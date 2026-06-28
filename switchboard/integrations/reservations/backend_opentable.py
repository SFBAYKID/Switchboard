"""OpenTableReservationsBackend — the REAL backend SEAM (NOT implemented yet).

This is the clearly-marked seam for the real OpenTable client. It is intentionally
NOT implemented: per CLAUDE.md Rule 2, the exact OpenTable endpoints, auth scheme,
request/response shapes, idempotency support, and error codes MUST be confirmed
against current official OpenTable documentation BEFORE this client is written — a
single wrong field on an integration boundary fails silently, or worse, books
incorrectly. Writing it from memory now would violate the project's top rules.

Go-live path (architecture.md "First module"):
  1. OpenTable partner approval lands (~3-week wait; blocks go-live, not build).
  2. Implement the four methods below against the REAL API, verified against the
     official docs. They must return the SAME `models.py` types the mock returns,
     so the caller-visible contract does not change.
  3. Flip `RESERVATIONS_BACKEND=opentable`. Only the envelope `mock` flag changes
     (true -> false); callers' requests are identical.

Until then, selecting this backend and calling it raises `NotImplementedError`,
which the dispatch layer surfaces as a safe `upstream_error` envelope. Keeping the
seam present (rather than absent) makes the swap a one-line config flip and keeps
the interface honest.
"""

from __future__ import annotations

from switchboard.core.credentials import ResolvedCredential
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

# A single, explicit message so a misconfiguration ("opentable" selected before the
# real client exists) is unmistakable in logs and errors.
_NOT_IMPLEMENTED = (
    "OpenTableReservationsBackend is a not-yet-implemented seam. The real client is "
    "written only after OpenTable partner approval, with every endpoint/auth/shape "
    "verified against official OpenTable docs first (CLAUDE.md Rule 2). Until then, "
    "use RESERVATIONS_BACKEND=mock."
)


class OpenTableReservationsBackend:
    """Real OpenTable client SEAM. Implements `ReservationsBackend`; not yet built."""

    def __init__(self) -> None:
        # When implemented, this will hold a reused HTTP client / connection pool.
        # Construction itself is allowed (so the registry can be exercised); only
        # actual calls raise, surfacing the seam clearly if it is selected too early.
        pass

    async def availability(
        self, req: AvailabilityRequest, cred: ResolvedCredential
    ) -> AvailabilityResult:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def book(
        self, req: BookingRequest, cred: ResolvedCredential
    ) -> BookingResult:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def modify(
        self, req: ModifyRequest, cred: ResolvedCredential
    ) -> ModifyResult:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def cancel(
        self, req: CancelRequest, cred: ResolvedCredential
    ) -> CancelResult:
        raise NotImplementedError(_NOT_IMPLEMENTED)
