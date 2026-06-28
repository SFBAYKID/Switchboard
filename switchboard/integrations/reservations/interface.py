"""The uniform reservations backend interface (a typed Protocol).

Every reservations backend — the MOCK now, the real OpenTable client later —
implements EXACTLY this interface. The API layer holds a reference to the Protocol,
never to a concrete vendor class, so it is blind to which backend is live. This is
the seam that makes the mock->real swap invisible to callers (architecture.md "The
uniform internal interface").

Each method receives the validated request model, the resolved per-tenant
`ResolvedCredential`, AND `deadline_ms` — the remaining budget in milliseconds
(review #4: deadline propagation). The mock ignores the secret and the deadline (the
dispatch layer's `asyncio.wait_for` enforces the budget for it), but the real
backend MUST use `deadline_ms` to bound its OWN upstream HTTP client so a slow vendor
call is aborted cleanly within budget rather than cancelled mid-flight — which, for a
consequential write, is what prevents an ambiguous partial write. The deadline is in
the signature now (before the real backend exists) so the seam shape is right.

Contract for outcomes (review #2/#3):
  - On a DEFINITIVE SUCCESS, a method returns its typed result. For booking that
    means an actual confirmation only.
  - On any NON-DEFINITIVE outcome it RAISES the matching `AppError` from
    `core.errors` (e.g. `RateLimitedOutcome`, `RequiresHumanOutcome`,
    `BookingUnavailableOutcome`) tagged with `source`/`mock`. A timeout is enforced
    by the dispatch layer; an unclassified exception is mapped to `unknown` there.
    A method must NEVER return a false success or leak a raw vendor error.
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
    signatures, not just names). It is intentionally NOT `@runtime_checkable`: an
    `isinstance` check would only verify method names, which would overstate the
    guarantee — the static check is the real one.
    """

    async def availability(
        self, req: AvailabilityRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> AvailabilityResult:
        """Return availability for the requested tenant/party/time (real-time)."""
        ...

    async def book(
        self, req: BookingRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> BookingResult:
        """Create a booking (consequential write; retry-safe via idempotency_key)."""
        ...

    async def modify(
        self, req: ModifyRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> ModifyResult:
        """Modify an existing booking (consequential write)."""
        ...

    async def cancel(
        self, req: CancelRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> CancelResult:
        """Cancel an existing booking (consequential write)."""
        ...
