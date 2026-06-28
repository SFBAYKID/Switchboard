"""The uniform reservations backend interface (a typed Protocol).

Every reservations backend — the MOCK now, the real OpenTable client later —
implements EXACTLY this interface. The API layer holds a reference to the Protocol,
never to a concrete vendor class, so it is blind to which backend is live. This is
the seam that makes the mock->real swap invisible to callers (architecture.md).

Each method receives the validated request model, the resolved per-restaurant
`ResolvedCredential` (which carries the OpenTable RID + API key), and `deadline_ms`
(the remaining budget — review #4; the real backend bounds its own HTTP client with
it, the mock relies on the dispatch timeout). WRITE methods also receive the
`idempotency_key` (from the required `Idempotency-Key` header) so a retried write is
de-duplicated (review #5).

Contract for outcomes (review #2/#3):
  - On a DEFINITIVE SUCCESS, a method returns its typed result. For booking that
    means an actual confirmation only.
  - On any NON-DEFINITIVE outcome it RAISES the matching `AppError` from
    `core.errors` (RateLimitedOutcome, RequiresHumanOutcome, BookingUnavailableOutcome,
    ReservationNotFoundError, …) tagged with `source`/`mock`. A timeout is enforced by
    the dispatch layer; an unclassified exception is mapped to `unknown` there. A
    method must NEVER return a false success or leak a raw vendor error.
"""

from __future__ import annotations

from typing import Protocol

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


class ReservationsBackend(Protocol):
    """Typed contract every reservations backend (mock or real) must satisfy.

    Conformance is enforced statically by mypy (structural typing checks the method
    signatures). Intentionally NOT `@runtime_checkable` — an isinstance check would
    only verify method names, overstating the guarantee; the static check is the real one.
    """

    async def availability(
        self, req: AvailabilityRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> AvailabilityResult:
        """Return availability for the requested restaurant/date/time/party (real-time)."""
        ...

    async def book(
        self,
        req: BookingRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> BookingResult:
        """Create a booking (consequential write; de-duplicated on idempotency_key)."""
        ...

    async def modify(
        self,
        req: ModifyRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> ModifyResult:
        """Modify an existing booking (consequential write)."""
        ...

    async def cancel(
        self,
        req: CancelRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> CancelResult:
        """Cancel an existing booking (consequential write)."""
        ...
