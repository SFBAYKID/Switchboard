"""MockReservationsBackend — fake-but-contract-shaped reservations data (DEFAULT).

A first-class backend, not a throwaway stub: it returns data shaped EXACTLY like the
real OpenTable backend will (same models, same envelope via the API layer), so the
entire caller -> gateway -> result loop is built, tested, and demoed BEFORE real
OpenTable access exists (architecture.md "Mock-first, and the real-swap").

HOSTILE by design (review #7): the mock can model the conditions real life produces,
so callers exercise their degrade paths BEFORE the real backend exists. It does NOT
just return the happy path. It exercises:
  - timeout / slow response  — via `delay_ms` (the dispatch deadline cancels it)
  - upstream auth failure     — `fail_mode="auth_error"`  -> AuthErrorOutcome
  - rate limiting             — `fail_mode="rate_limited"` -> RateLimitedOutcome
  - malformed / unusable data — `fail_mode="unknown"`      -> UnknownOutcome
  - no availability           — party_size > MAX_ONLINE_PARTY -> state "unavailable"
  - booking-after-apparent-availability race (review #5):
        `fail_mode="booking_race"` on book -> RequiresHumanOutcome (ambiguous) or,
        when the slot is simply gone, BookingUnavailableOutcome — NEVER a false
        confirmation.

These knobs are mock-only config, NOT part of the public API contract. Mock mode is
additionally refused in production unless an explicit flag is set (see core.config) —
review #7 "impossible to use in production without an explicit flag."

Determinism: a booking's confirmation id is a pure function of (tenant,
idempotency_key), so tests are stable AND a retried `book` with the same key returns
the SAME confirmation_id (idempotent — no double-booking, review #5). The key is
REQUIRED (enforced by the request model), so there is no content-hash fallback that
could collide two genuinely distinct bookings into one (false) confirmation. No
randomness, no clock reads, no persisted state (stateless, like the real
upstream-is-source-of-truth posture).

`deadline_ms` (the remaining budget) is accepted for interface conformance but the
mock does not act on it — the dispatch layer's timeout enforces the budget for the
mock; the REAL backend will use it to bound its upstream HTTP client. The resolved
credential is accepted but its secret is NEVER used, logged, or echoed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib

from switchboard.core.credentials import ResolvedCredential
from switchboard.core.errors import (
    AuthErrorOutcome,
    BookingUnavailableOutcome,
    RateLimitedOutcome,
    RequiresHumanOutcome,
    UnknownOutcome,
)
from switchboard.integrations.reservations import SOURCE
from switchboard.integrations.reservations.models import (
    AvailabilityRequest,
    AvailabilityResult,
    AvailabilitySlot,
    BookingRequest,
    BookingResult,
    CancelRequest,
    CancelResult,
    ModifyRequest,
    ModifyResult,
)

# Above this party size the mock reports no online availability (realistic).
MAX_ONLINE_PARTY: int = 12

# How many candidate slots the mock offers around the requested time, and the gap.
_SLOT_COUNT: int = 3
_SLOT_STEP = dt.timedelta(minutes=30)

# fail_mode values that map directly to a raised normalized outcome (applied to read
# AND write calls). `booking_race` is handled specially in book() only.
_DIRECT_FAIL_OUTCOMES = {
    "auth_error": AuthErrorOutcome,
    "rate_limited": RateLimitedOutcome,
    "unknown": UnknownOutcome,
}


def _confirmation_id(tenant: str, idempotency_key: str) -> str:
    """Deterministically derive a confirmation id from (tenant, idempotency_key).

    Pure function: the same key always yields the same id, so a retried booking
    returns the identical confirmation_id (idempotent — no double-book, review #5).
    """

    digest = hashlib.sha256(f"{tenant}:{idempotency_key}".encode()).hexdigest()
    return f"MOCK-{tenant.upper()}-{digest[:12].upper()}"


class MockReservationsBackend:
    """In-process hostile fake reservations backend implementing `ReservationsBackend`."""

    def __init__(self, *, delay_ms: int = 0, fail_mode: str = "none") -> None:
        # Mock-only config (see module docstring). Defaults = instant, never-fail.
        self._delay_ms: int = delay_ms
        self._fail_mode: str = fail_mode

    async def _simulate_upstream(self) -> None:
        """Apply the configured artificial delay and direct failure outcomes.

        The delay lets tests/dev trip the deadline budget; the dispatch layer's
        timeout cancels this sleep and returns a `timeout` outcome. A direct
        fail_mode raises the matching normalized outcome (auth_error/rate_limited/
        unknown) — all tagged source=reservations, mock=True so the envelope
        attributes the failure correctly. `booking_race` is NOT handled here (it is
        book-specific).
        """

        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)
        outcome = _DIRECT_FAIL_OUTCOMES.get(self._fail_mode)
        if outcome is not None:
            raise outcome(source=SOURCE, mock=True)

    async def availability(
        self, req: AvailabilityRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> AvailabilityResult:
        await self._simulate_upstream()

        # Realistic "no online availability" for very large parties.
        if req.party_size > MAX_ONLINE_PARTY:
            return AvailabilityResult(state="unavailable", slots=[])

        # Otherwise offer a few deterministic candidate slots around the requested
        # time. Deterministic (derived from req.datetime), so tests are stable.
        slots = [
            AvailabilitySlot(
                time=req.datetime + (_SLOT_STEP * i),
                party_size=req.party_size,
            )
            for i in range(_SLOT_COUNT)
        ]
        return AvailabilityResult(state="available", slots=slots)

    async def book(
        self, req: BookingRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> BookingResult:
        await self._simulate_upstream()

        # Review #5: the availability != booked race. The slot can vanish between the
        # availability check and the booking. The mock models BOTH ambiguous and
        # slot-gone outcomes, and NEVER returns a false confirmation.
        if self._fail_mode == "booking_race":
            # Ambiguous: the upstream may have accepted but we lost the confirmation
            # -> a human must reconcile (do not blind-retry a possible write).
            raise RequiresHumanOutcome(source=SOURCE, mock=True)
        if self._fail_mode == "slot_gone":
            # Definitive: the slot is gone -> unavailable, no confirmation.
            raise BookingUnavailableOutcome(source=SOURCE, mock=True)

        # Idempotent confirmation id, keyed on the REQUIRED idempotency_key: a retry
        # with the same key returns the same id (no double-book, review #5).
        return BookingResult(
            state="confirmed",
            confirmation_id=_confirmation_id(req.tenant, req.idempotency_key),
        )

    async def modify(
        self, req: ModifyRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> ModifyResult:
        await self._simulate_upstream()

        # The mock is stateless: it echoes the confirmation id and reports modified.
        # (A real backend validates the id upstream and may raise an outcome.)
        return ModifyResult(state="modified", confirmation_id=req.confirmation_id)

    async def cancel(
        self, req: CancelRequest, cred: ResolvedCredential, deadline_ms: int
    ) -> CancelResult:
        await self._simulate_upstream()

        return CancelResult(state="cancelled", confirmation_id=req.confirmation_id)
