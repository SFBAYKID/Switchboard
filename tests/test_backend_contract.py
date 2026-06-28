"""Backend-agnostic contract test (the mock↔real parity guard — QA finding M2).

The highest-leverage correctness risk in a mock-first gateway is the mock and the
real backend diverging. mypy's structural Protocol check guards the SIGNATURES; this
suite guards the runtime SHAPES + state vocabulary of the results.

Parametrized so the real `OpenTableReservationsBackend` can be added the moment it
exists (against the sandbox) and must pass the EXACT same assertions. Today only the
mock is exercised: verified-on-mock, NOT verified-against-real. The autouse fixture
resets the mock store before each test.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest

from switchboard.core.credentials import ResolvedCredential
from switchboard.integrations.reservations.backend_mock import MockReservationsBackend
from switchboard.integrations.reservations.interface import ReservationsBackend
from switchboard.integrations.reservations.mock_store import get_store
from switchboard.integrations.reservations.models import (
    AvailabilityRequest,
    AvailabilityResult,
    BookingRequest,
    BookingResult,
    CancelRequest,
    CancelResult,
    Customer,
    ModifyRequest,
    ModifyResult,
)

# DEMO is seeded in the mock store. Credential secret is irrelevant to the mock.
CRED = ResolvedCredential(integration="OPENTABLE", tenant="DEMO", api_key="unused", rid="r")
DATE = dt.date(2026, 7, 1)
TIME = "19:00"  # a seeded slot for DEMO
DEADLINE_MS = 1000
CUSTOMER = Customer(name="Ada", phone="+14155551212")


@pytest.fixture
def backend() -> Iterator[ReservationsBackend]:
    """Each contract backend, freshly pointed at the (reset-between-tests) store.

    Add OpenTableReservationsBackend here (sandbox) once it exists — it must pass
    every assertion below unchanged.
    """

    yield MockReservationsBackend(get_store())


async def test_availability_shape(backend: ReservationsBackend) -> None:
    result = await backend.availability(
        AvailabilityRequest(restaurant_id="demo", date=DATE, time=TIME, party_size=2),
        CRED,
        DEADLINE_MS,
    )
    assert isinstance(result, AvailabilityResult)
    assert result.state in {"available", "unavailable"}
    for slot in result.slots:
        assert slot.party_size >= 1


async def test_book_shape_and_idempotency(backend: ReservationsBackend) -> None:
    req = BookingRequest(
        restaurant_id="demo", date=DATE, time=TIME, party_size=2, customer=CUSTOMER
    )
    first = await backend.book(req, CRED, DEADLINE_MS, "same")
    assert isinstance(first, BookingResult)
    assert first.state == "confirmed"
    assert first.confirmation_id
    # Same idempotency key => same confirmation (no double-book).
    second = await backend.book(req, CRED, DEADLINE_MS, "same")
    assert second.confirmation_id == first.confirmation_id


async def test_modify_shape(backend: ReservationsBackend) -> None:
    cid = (
        await backend.book(
            BookingRequest(restaurant_id="demo", date=DATE, time=TIME, party_size=2, customer=CUSTOMER),
            CRED,
            DEADLINE_MS,
            "m",
        )
    ).confirmation_id
    result = await backend.modify(
        ModifyRequest(restaurant_id="demo", confirmation_id=cid), CRED, DEADLINE_MS, "m2"
    )
    assert isinstance(result, ModifyResult)
    assert result.state == "modified"
    assert result.confirmation_id == cid


async def test_cancel_shape(backend: ReservationsBackend) -> None:
    cid = (
        await backend.book(
            BookingRequest(restaurant_id="demo", date=DATE, time=TIME, party_size=2, customer=CUSTOMER),
            CRED,
            DEADLINE_MS,
            "c",
        )
    ).confirmation_id
    result = await backend.cancel(
        CancelRequest(restaurant_id="demo", confirmation_id=cid), CRED, DEADLINE_MS, "c2"
    )
    assert isinstance(result, CancelResult)
    assert result.state == "cancelled"
    assert result.confirmation_id == cid
