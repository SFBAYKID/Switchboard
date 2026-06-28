"""In-memory, JSON-seeded STATEFUL store for the reservations MOCK backend.

Why this exists (and why it lives only in the MOCK): the real OpenTable upstream is
the stateful system of record. To let the calling agent exercise the FULL lifecycle
against the mock during the partner-approval wait — check a specific date/time, book
it (consuming the slot), see availability change, modify it, cancel it — the mock must
behave like a small stateful reservation system, not echo canned responses.

Switchboard itself stays STATELESS (architecture.md "Data posture"). This store lives
inside the MOCK backend, standing in for the upstream's state; it is NOT a Switchboard
datastore and has no bearing on the real backend, which will call OpenTable instead.

Seed: loaded from a JSON file (default `data/mock_reservations.json`, override with
`MOCK_RESERVATIONS_SEED_PATH`). Bookings/cancellations are kept in-process and reset
to the seed on restart. The store is a process singleton so state persists across
requests; tests call `reset_store()` between tests (it resets state IN PLACE, so
existing references stay valid).

Concurrency: each method does its read-check-then-mutate synchronously (no `await`
between), so under the single-threaded asyncio event loop every mutation is atomic.

Restaurant scoping is a real isolation boundary: reservations are stored per
restaurant, so one restaurant can never look up, modify, or cancel another's.
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
    combined_datetime,
)


# ── Store-level exceptions (translated to normalized AppErrors by the backend) ────
class SlotUnavailable(Exception):
    """No remaining capacity for the requested slot (the availability!=booked race)."""


class ReservationMissing(Exception):
    """No such reservation for this restaurant (unknown id, or it belongs to another)."""


# ── Internal state ───────────────────────────────────────────────────────────────
@dataclass
class _Slot:
    """A bookable slot with finite capacity. `booked` rises as bookings consume it."""

    when: dt.datetime  # combined date+time (slot key)
    capacity: int
    booked: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.booked)


@dataclass
class _Reservation:
    """A reservation record (the mock's stand-in for an OpenTable booking)."""

    confirmation_id: str
    restaurant_id: str
    name: str
    phone: str
    party_size: int
    when: dt.datetime
    status: str  # "confirmed" | "modified" | "cancelled"
    idempotency_key: str


@dataclass
class _RestaurantState:
    slots: list[_Slot] = field(default_factory=list)
    reservations: dict[str, _Reservation] = field(default_factory=dict)
    # idempotency_key -> confirmation_id, so a retried book reuses the same booking.
    idempotency_index: dict[str, str] = field(default_factory=dict)


def _confirmation_id(restaurant_id: str, idempotency_key: str) -> str:
    """Deterministic confirmation id from (restaurant_id, idempotency_key)."""

    digest = hashlib.sha256(f"{restaurant_id}:{idempotency_key}".encode()).hexdigest()
    return f"MOCK-{restaurant_id.upper()}-{digest[:12].upper()}"


class MockReservationStore:
    """Stateful, JSON-seeded reservation store for the mock backend."""

    def __init__(self, seed_path: pathlib.Path) -> None:
        self._seed_path = seed_path
        self._restaurants: dict[str, _RestaurantState] = {}
        self.reset_to_seed()

    def reset_to_seed(self) -> None:
        """(Re)load slots from the seed file and clear all runtime reservations."""

        data = json.loads(self._seed_path.read_text())
        restaurants: dict[str, _RestaurantState] = {}
        # Seed schema: { "restaurants": { "<RESTAURANT_ID>": { "slots": [ {date, time,
        # capacity} ] } } }. Each slot: date YYYY-MM-DD, time HH:MM, capacity int.
        for rid, info in data["restaurants"].items():
            slots = [
                _Slot(
                    when=combined_datetime(dt.date.fromisoformat(s["date"]), s["time"]),
                    capacity=int(s["capacity"]),
                )
                for s in info.get("slots", [])
            ]
            restaurants[rid.upper()] = _RestaurantState(slots=slots)
        self._restaurants = restaurants

    def _restaurant(self, restaurant_id: str) -> _RestaurantState:
        # A configured restaurant with no seed entry simply has no slots.
        return self._restaurants.setdefault(restaurant_id.upper(), _RestaurantState())

    def query_availability(
        self, restaurant_id: str, req_when: dt.datetime, party_size: int
    ) -> AvailabilityResult:
        """`available` iff the requested slot is open; `slots` = open slots that day."""

        state = self._restaurant(restaurant_id)
        same_day_open = [s for s in state.slots if s.remaining > 0 and s.when.date() == req_when.date()]
        requested_open = any(s.when == req_when for s in same_day_open)
        slots = [
            AvailabilitySlot(
                date=s.when.date(), time=s.when.strftime("%H:%M"), party_size=party_size
            )
            for s in sorted(same_day_open, key=lambda s: s.when)
        ]
        return AvailabilityResult(
            state="available" if requested_open else "unavailable", slots=slots
        )

    def create_booking(
        self, restaurant_id: str, req: BookingRequest, idempotency_key: str
    ) -> BookingResult:
        """Create a booking, consuming slot capacity. Idempotent on idempotency_key.

        Raises:
            SlotUnavailable: the requested slot has no remaining capacity (race).
        """

        state = self._restaurant(restaurant_id)

        # Idempotency: a retried book with the same key returns the SAME booking and
        # does NOT consume capacity again (no double-book).
        existing_id = state.idempotency_index.get(idempotency_key)
        if existing_id is not None:
            return BookingResult(state="confirmed", confirmation_id=existing_id)

        req_when = combined_datetime(req.date, req.time)
        slot = next((s for s in state.slots if s.when == req_when and s.remaining > 0), None)
        if slot is None:
            raise SlotUnavailable()

        confirmation_id = _confirmation_id(restaurant_id, idempotency_key)
        slot.booked += 1
        state.reservations[confirmation_id] = _Reservation(
            confirmation_id=confirmation_id,
            restaurant_id=restaurant_id.upper(),
            name=req.customer.name,
            phone=req.customer.phone,
            party_size=req.party_size,
            when=req_when,
            status="confirmed",
            idempotency_key=idempotency_key,
        )
        state.idempotency_index[idempotency_key] = confirmation_id
        return BookingResult(state="confirmed", confirmation_id=confirmation_id)

    def modify_booking(self, restaurant_id: str, req: ModifyRequest) -> ModifyResult:
        """Modify an existing (non-cancelled) reservation for this restaurant.

        Raises:
            ReservationMissing: no such reservation for this restaurant (or cancelled).
        """

        state = self._restaurant(restaurant_id)
        reservation = state.reservations.get(req.confirmation_id)
        if reservation is None or reservation.status == "cancelled":
            raise ReservationMissing()

        if req.party_size is not None:
            reservation.party_size = req.party_size
        if req.date is not None and req.time is not None:
            reservation.when = combined_datetime(req.date, req.time)
        reservation.status = "modified"
        return ModifyResult(state="modified", confirmation_id=reservation.confirmation_id)

    def cancel_booking(self, restaurant_id: str, req: CancelRequest) -> CancelResult:
        """Cancel a reservation for this restaurant, freeing its slot. Idempotent.

        Raises:
            ReservationMissing: no such reservation for this restaurant.
        """

        state = self._restaurant(restaurant_id)
        reservation = state.reservations.get(req.confirmation_id)
        if reservation is None:
            raise ReservationMissing()
        if reservation.status == "cancelled":
            return CancelResult(state="cancelled", confirmation_id=reservation.confirmation_id)

        slot = next((s for s in state.slots if s.when == reservation.when), None)
        if slot is not None:
            slot.booked = max(0, slot.booked - 1)
        reservation.status = "cancelled"
        return CancelResult(state="cancelled", confirmation_id=reservation.confirmation_id)


# ── Process-singleton accessors ──────────────────────────────────────────────────
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
