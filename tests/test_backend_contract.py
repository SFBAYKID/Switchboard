"""Backend-agnostic contract test (the mock↔real parity guard — QA finding M2).

The highest-leverage correctness risk in a mock-first gateway is the mock and the
real backend diverging, so everything "works in mock" and breaks the day real
OpenTable is wired in. mypy's structural Protocol check guards the SIGNATURES; this
suite guards the runtime SHAPES + state vocabulary of the results.

It is parametrized so the real `OpenTableReservationsBackend` can be added the moment
it exists (against the sandbox) and must pass the EXACT same assertions — that is what
makes the swap safe. Today only the mock is exercised; this is verified-on-mock, not
verified-against-real (honest split). The autouse fixture resets the mock store before
each test, so state from one test never leaks into another.
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
    ModifyRequest,
    ModifyResult,
)

# A resolved credential is required by the interface; its secret value is irrelevant
# to the mock and is never used/echoed. DEMO is seeded in the mock store.
CRED = ResolvedCredential(integration="OPENTABLE", tenant="DEMO", api_key="unused", rid="r")
WHEN = dt.datetime(2026, 7, 1, 19, 0, 0)  # a seeded slot for DEMO
DEADLINE_MS = 1000


@pytest.fixture
def backend() -> Iterator[ReservationsBackend]:
    """Each contract backend, freshly pointed at the (reset-between-tests) store.

    Add OpenTableReservationsBackend here (sandbox) once it exists — it must pass
    every assertion below unchanged.
    """

    yield MockReservationsBackend(get_store())


async def test_availability_shape(backend: ReservationsBackend) -> None:
    result = await backend.availability(
        AvailabilityRequest(tenant="demo", party_size=2, datetime=WHEN), CRED, DEADLINE_MS
    )
    assert isinstance(result, AvailabilityResult)
    assert result.state in {"available", "unavailable"}
    for slot in result.slots:
        assert slot.party_size >= 1


async def test_book_shape_and_idempotency(backend: ReservationsBackend) -> None:
    req = BookingRequest(
        tenant="demo", name="Ada", party_size=2, datetime=WHEN, idempotency_key="same"
    )
    first = await backend.book(req, CRED, DEADLINE_MS)
    assert isinstance(first, BookingResult)
    assert first.state == "confirmed"
    assert first.confirmation_id
    # Same idempotency key => same confirmation (no double-book).
    second = await backend.book(req, CRED, DEADLINE_MS)
    assert second.confirmation_id == first.confirmation_id


async def test_modify_shape(backend: ReservationsBackend) -> None:
    cid = (
        await backend.book(
            BookingRequest(
                tenant="demo", name="Ada", party_size=2, datetime=WHEN, idempotency_key="m"
            ),
            CRED,
            DEADLINE_MS,
        )
    ).confirmation_id
    result = await backend.modify(
        ModifyRequest(tenant="demo", confirmation_id=cid, idempotency_key="m2"),
        CRED,
        DEADLINE_MS,
    )
    assert isinstance(result, ModifyResult)
    assert result.state == "modified"
    assert result.confirmation_id == cid


async def test_cancel_shape(backend: ReservationsBackend) -> None:
    cid = (
        await backend.book(
            BookingRequest(
                tenant="demo", name="Ada", party_size=2, datetime=WHEN, idempotency_key="c"
            ),
            CRED,
            DEADLINE_MS,
        )
    ).confirmation_id
    result = await backend.cancel(
        CancelRequest(tenant="demo", confirmation_id=cid, idempotency_key="c2"),
        CRED,
        DEADLINE_MS,
    )
    assert isinstance(result, CancelResult)
    assert result.state == "cancelled"
    assert result.confirmation_id == cid
