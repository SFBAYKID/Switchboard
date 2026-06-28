"""MockReservationsBackend — STATEFUL, JSON-seeded fake reservations (DEFAULT).

A first-class backend, not a throwaway stub: it returns data shaped EXACTLY like the
real OpenTable backend will (same models, same envelope via the API layer), so the
entire caller -> gateway -> result loop is built, tested, and demoed BEFORE real
OpenTable access exists (architecture.md "Mock-first, and the real-swap").

It is backed by a stateful, JSON-seeded store (`mock_store.py`) so a caller can
exercise the FULL lifecycle: `book` creates a reservation and consumes slot capacity,
`availability` reflects what's left, `modify`/`cancel` act on the real record, and an
unknown/foreign reservation fails like the upstream would. The store stands in for
OpenTable's state; Switchboard itself stays stateless.

HOSTILE by design (review #7): independent of the stateful data, the mock can FORCE
adverse conditions so callers exercise their degrade paths on demand:
  - timeout / slow response   — `delay_ms` (the dispatch deadline cancels it)
  - upstream auth failure      — `fail_mode="auth_error"`  -> AuthErrorOutcome
  - rate limiting              — `fail_mode="rate_limited"` -> RateLimitedOutcome
  - malformed / unusable data  — `fail_mode="unknown"`      -> UnknownOutcome
  - ambiguous booking race     — `fail_mode="booking_race"` -> RequiresHumanOutcome
  - slot gone                  — `fail_mode="slot_gone"`    -> BookingUnavailableOutcome
The natural race also occurs without injection: book a capacity-1 slot twice and the
second returns `unavailable`. These knobs are mock-only config, NOT part of the public
contract, and mock mode is refused in production without an explicit flag (core.config).

`deadline_ms` is accepted for interface conformance but the mock does not act on it —
the dispatch layer's timeout enforces the budget; the REAL backend will use it to
bound its upstream HTTP client. The resolved credential is accepted but its secret is
NEVER used, logged, or echoed.
"""

from __future__ import annotations

import asyncio

from switchboard.core.credentials import ResolvedCredential
from switchboard.core.errors import (
    AuthErrorOutcome,
    BookingUnavailableOutcome,
    RateLimitedOutcome,
    RequiresHumanOutcome,
    ReservationNotFoundError,
    UnknownOutcome,
)
from switchboard.integrations.reservations import SOURCE
from switchboard.integrations.reservations.models import (
    AvailabilityRequest,
    AvailabilityResult,
    BookingRequest,
    BookingResult,
    CancelRequest,
    CancelResult,
    ModifyRequest,
    ModifyResult,
    combined_datetime,
)
from switchboard.integrations.reservations.mock_store import (
    MockReservationStore,
    ReservationMissing,
    SlotUnavailable,
)

# Above this party size the mock reports no online availability (realistic).
MAX_ONLINE_PARTY: int = 12

# fail_mode values that map directly to a raised normalized outcome (applied to read
# AND write calls). `booking_race` / `slot_gone` are handled in book() only.
_DIRECT_FAIL_OUTCOMES = {
    "auth_error": AuthErrorOutcome,
    "rate_limited": RateLimitedOutcome,
    "unknown": UnknownOutcome,
}


class MockReservationsBackend:
    """Stateful, hostile, in-process fake backend implementing `ReservationsBackend`."""

    def __init__(
        self,
        store: MockReservationStore,
        *,
        delay_ms: int = 0,
        fail_mode: str = "none",
    ) -> None:
        self._store = store
        self._delay_ms = delay_ms
        self._fail_mode = fail_mode

    async def _simulate_upstream(self) -> None:
        """Apply the configured artificial delay and direct failure outcomes.

        The delay lets tests/dev trip the deadline budget; the dispatch layer's
        timeout cancels this sleep and returns a `timeout` outcome. A direct
        fail_mode raises the matching normalized outcome (auth_error/rate_limited/
        unknown), tagged source=reservations, mock=True. `booking_race`/`slot_gone`
        are NOT handled here (they are book-specific).
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

        # Otherwise reflect the live store (slots minus what's been booked).
        return self._store.query_availability(
            cred.tenant, combined_datetime(req.date, req.time), req.party_size
        )

    async def book(
        self,
        req: BookingRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> BookingResult:
        await self._simulate_upstream()

        # Forced race outcomes (review #5) — never a false confirmation.
        if self._fail_mode == "booking_race":
            raise RequiresHumanOutcome(source=SOURCE, mock=True)
        if self._fail_mode == "slot_gone":
            raise BookingUnavailableOutcome(source=SOURCE, mock=True)

        try:
            # Stateful + idempotent: same idempotency_key returns the same booking;
            # an exhausted slot is the natural availability!=booked race.
            return self._store.create_booking(cred.tenant, req, idempotency_key)
        except SlotUnavailable as exc:
            raise BookingUnavailableOutcome(source=SOURCE, mock=True) from exc

    async def modify(
        self,
        req: ModifyRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> ModifyResult:
        await self._simulate_upstream()

        try:
            return self._store.modify_booking(cred.tenant, req)
        except ReservationMissing as exc:
            # Restaurant-scoped lookup: unknown id, or it belongs to another restaurant.
            raise ReservationNotFoundError(source=SOURCE, mock=True) from exc

    async def cancel(
        self,
        req: CancelRequest,
        cred: ResolvedCredential,
        deadline_ms: int,
        idempotency_key: str,
    ) -> CancelResult:
        await self._simulate_upstream()

        try:
            return self._store.cancel_booking(cred.tenant, req)
        except ReservationMissing as exc:
            raise ReservationNotFoundError(source=SOURCE, mock=True) from exc
