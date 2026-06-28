"""The uniform reservations backend interface (a typed Protocol).

Every reservations backend — the MOCK now, the real OpenTable client later —
implements EXACTLY this interface. The API layer holds a reference to the Protocol,
never to a concrete vendor class, so it is blind to which backend is live. This is
the seam that makes the mock->real swap invisible to callers (architecture.md "The
uniform internal interface").

Each method receives the validated request model AND the resolved per-tenant
`ResolvedCredential`. The mock ignores the secret (it makes no real call) but still
receives it so the credential-resolution + isolation path is exercised identically
to the real backend. The real backend uses it to authenticate upstream.

Contract for outcomes (review #2/#3):
  - On a DEFINITIVE SUCCESS, a method returns its typed result (the success state +
    payload). For booking that means an actual confirmation only.
  - On any NON-DEFINITIVE outcome it RAISES the matching `AppError` from
    `core.errors` (e.g. `RateLimitedOutcome`, `RequiresHumanOutcome`,
    `BookingUnavailableOutcome`) tagged with `source`/`mock`. A timeout is enforced
    by the dispatch layer; an unclassified exception is mapped to `unknown` there.
    A method must NEVER return a false success or leak a raw vendor error.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class ReservationsBackend(Protocol):
    """Typed contract every reservations backend (mock or real) must satisfy."""

    async def availability(
        self, req: AvailabilityRequest, cred: ResolvedCredential
    ) -> AvailabilityResult:
        """Return availability for the requested tenant/party/time (real-time)."""
        ...

    async def book(
        self, req: BookingRequest, cred: ResolvedCredential
    ) -> BookingResult:
        """Create a booking (consequential write; retry-safe via idempotency_key)."""
        ...

    async def modify(
        self, req: ModifyRequest, cred: ResolvedCredential
    ) -> ModifyResult:
        """Modify an existing booking (consequential write)."""
        ...

    async def cancel(
        self, req: CancelRequest, cred: ResolvedCredential
    ) -> CancelResult:
        """Cancel an existing booking (consequential write)."""
        ...
