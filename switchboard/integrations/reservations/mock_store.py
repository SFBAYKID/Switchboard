"""In-memory, JSON-seeded STATEFUL store for the reservations MOCK backend.

Why this exists (and why it lives only in the MOCK): the real OpenTable upstream is
the stateful system of record. To let a calling agent exercise the FULL lifecycle
against the mock during the partner-approval wait — book a reservation, watch it
consume a slot, modify it, cancel it, and have availability reflect all of that — the
mock must behave like a small stateful reservation system, not echo canned responses.

Switchboard itself stays STATELESS (architecture.md "Data posture"). This store lives
inside the MOCK backend, standing in for the upstream's state; it is NOT a Switchboard
datastore and has no bearing on the real backend, which will call OpenTable instead.

Seed: loaded from a JSON file (default `data/mock_reservations.json`, override with
`MOCK_RESERVATIONS_SEED_PATH`). Bookings/cancellations are kept in-process and reset
to the seed on restart — exactly right for a disposable dummy. The store is a process
singleton so state persists across requests; tests call `reset_store()` between tests
(it resets state IN PLACE, so existing references stay valid).

Concurrency: each method does its read-check-then-mutate synchronously (no `await`
between), so under the single-threaded asyncio event loop every mutation is atomic.
Intended for a single-process dev/test server.

Tenant scoping is a real isolation boundary here: reservations are stored per tenant,
so one tenant can never look up, modify, or cancel another tenant's reservation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
from dataclasses import dataclass, field

from switchboard.integrations.reservations.models import (
    AvailabilityResult,
    AvailabilitySlot,
    BookingRequest,
    BookingResult,
    CancelRequest,
    CancelResult,
    ModifyRequest,
    ModifyResult,
)


# ── Store-level exceptions (translated to normalized AppErrors by the backend) ────
class SlotUnavailable(Exception):
    """No remaining capacity for the requested slot (the availability!=booked race)."""


class ReservationMissing(Exception):
    """No such reservation for this tenant (unknown id, or it belongs to another)."""


# ── Internal state ───────────────────────────────────────────────────────────────
@dataclass
class _Slot:
    """A bookable slot with finite capacity. `booked` rises as bookings consume it."""

    time: dt.datetime
    capacity: int
    booked: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.booked)


@dataclass
class _Reservation:
    """A reservation record (the mock's stand-in for an OpenTable booking)."""

    confirmation_id: str
    tenant: str
    name: str
    party_size: int
    time: dt.datetime
    status: str  # "confirmed" | "modified" | "cancelled"
    idempotency_key: str


@dataclass
class _TenantState:
    slots: list[_Slot] = field(default_factory=list)
    reservations: dict[str, _Reservation] = field(default_factory=dict)
    # idempotency_key -> confirmation_id, so a retried book reuses the same booking.
    idempotency_index: dict[str, str] = field(default_factory=dict)


def _confirmation_id(tenant: str, idempotency_key: str) -> str:
    """Deterministic confirmation id from (tenant, idempotency_key) — idempotent."""

    digest = hashlib.sha256(f"{tenant}:{idempotency_key}".encode()).hexdigest()
    return f"MOCK-{tenant.upper()}-{digest[:12].upper()}"


class MockReservationStore:
    """Stateful, JSON-seeded reservation store for the mock backend."""

    def __init__(self, seed_path: pathlib.Path) -> None:
        self._seed_path = seed_path
        self._tenants: dict[str, _TenantState] = {}
        self.reset_to_seed()

    def reset_to_seed(self) -> None:
        """(Re)load slots from the seed file and clear all runtime reservations.

        Resets state IN PLACE so existing references to this store stay valid (the
        API constructs a backend per request that points here; tests reset between
        runs).
        """

        data = json.loads(self._seed_path.read_text())
        tenants: dict[str, _TenantState] = {}
        for tenant_name, tenant_info in data.get("tenants", {}).items():
            slots = [
                _Slot(time=dt.datetime.fromisoformat(s["time"]), capacity=int(s["capacity"]))
                for s in tenant_info.get("slots", [])
            ]
            tenants[tenant_name.upper()] = _TenantState(slots=slots)
        self._tenants = tenants

    def _tenant(self, tenant: str) -> _TenantState:
        # A configured tenant with no seed entry simply has no slots (bookings will
        # be unavailable) — never a KeyError.
        return self._tenants.setdefault(tenant.upper(), _TenantState())

    def query_availability(
        self, tenant: str, party_size: int, when: dt.datetime
    ) -> AvailabilityResult:
        """Return slots with remaining capacity on the requested date."""

        state = self._tenant(tenant)
        slots = [
            AvailabilitySlot(time=s.time, party_size=party_size)
            for s in state.slots
            if s.remaining > 0 and s.time.date() == when.date()
        ]
        return AvailabilityResult(
            state="available" if slots else "unavailable", slots=slots
        )

    def create_booking(self, tenant: str, req: BookingRequest) -> BookingResult:
        """Create a booking, consuming slot capacity. Idempotent on idempotency_key.

        Raises:
            SlotUnavailable: the requested slot has no remaining capacity (race).
        """

        state = self._tenant(tenant)

        # Idempotency: a retried book with the same key returns the SAME booking and
        # does NOT consume capacity again (no double-book).
        existing_id = state.idempotency_index.get(req.idempotency_key)
        if existing_id is not None:
            return BookingResult(state="confirmed", confirmation_id=existing_id)

        slot = next(
            (s for s in state.slots if s.time == req.datetime and s.remaining > 0),
            None,
        )
        if slot is None:
            raise SlotUnavailable()

        confirmation_id = _confirmation_id(tenant, req.idempotency_key)
        slot.booked += 1
        state.reservations[confirmation_id] = _Reservation(
            confirmation_id=confirmation_id,
            tenant=tenant.upper(),
            name=req.name,
            party_size=req.party_size,
            time=req.datetime,
            status="confirmed",
            idempotency_key=req.idempotency_key,
        )
        state.idempotency_index[req.idempotency_key] = confirmation_id
        return BookingResult(state="confirmed", confirmation_id=confirmation_id)

    def modify_booking(self, tenant: str, req: ModifyRequest) -> ModifyResult:
        """Modify an existing (non-cancelled) reservation for this tenant.

        Raises:
            ReservationMissing: no such reservation for this tenant (or cancelled).
        """

        state = self._tenant(tenant)
        reservation = state.reservations.get(req.confirmation_id)
        if reservation is None or reservation.status == "cancelled":
            raise ReservationMissing()

        if req.party_size is not None:
            reservation.party_size = req.party_size
        if req.datetime is not None:
            reservation.time = req.datetime
        reservation.status = "modified"
        return ModifyResult(state="modified", confirmation_id=reservation.confirmation_id)

    def cancel_booking(self, tenant: str, req: CancelRequest) -> CancelResult:
        """Cancel a reservation for this tenant, freeing its slot. Idempotent.

        Raises:
            ReservationMissing: no such reservation for this tenant.
        """

        state = self._tenant(tenant)
        reservation = state.reservations.get(req.confirmation_id)
        if reservation is None:
            raise ReservationMissing()
        if reservation.status == "cancelled":
            # Cancelling an already-cancelled booking is a safe no-op (idempotent).
            return CancelResult(state="cancelled", confirmation_id=reservation.confirmation_id)

        # Free the slot capacity this reservation held.
        slot = next((s for s in state.slots if s.time == reservation.time), None)
        if slot is not None:
            slot.booked = max(0, slot.booked - 1)
        reservation.status = "cancelled"
        return CancelResult(state="cancelled", confirmation_id=reservation.confirmation_id)


# ── Process-singleton accessors ──────────────────────────────────────────────────
# Repo root is three parents up from this file (.../switchboard/integrations/reservations).
_DEFAULT_SEED_PATH = (
    pathlib.Path(__file__).resolve().parents[3] / "data" / "mock_reservations.json"
)

_store: MockReservationStore | None = None


def _resolve_seed_path(seed_path: str | None) -> pathlib.Path:
    if seed_path:
        return pathlib.Path(seed_path)
    env_path = os.environ.get("MOCK_RESERVATIONS_SEED_PATH")
    if env_path:
        return pathlib.Path(env_path)
    return _DEFAULT_SEED_PATH


def get_store(seed_path: str | None = None) -> MockReservationStore:
    """Return the process-singleton mock store (created once from the seed)."""

    global _store
    if _store is None:
        _store = MockReservationStore(_resolve_seed_path(seed_path))
    return _store


def reset_store() -> None:
    """Reset the mock store to its seed IN PLACE (tests call this between runs)."""

    if _store is not None:
        _store.reset_to_seed()
