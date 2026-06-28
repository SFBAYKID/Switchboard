"""Stateful dummy-data behavior: lifecycle, the natural race, and tenant isolation.

These exercise the JSON-seeded stateful mock store end-to-end through the API — the
behavior a calling agent will rely on while testing its integration during the
OpenTable approval wait. Verified-on-mock (the real backend will behave equivalently
against OpenTable's state once wired in).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import (
    auth_headers,
    availability_payload,
    booking_payload,
    cancel_payload,
    modify_payload,
)

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"
MODIFY = "/v1/reservations/modify"
CANCEL = "/v1/reservations/cancel"

# A capacity-1 seed slot for DEMO/ACME (data/mock_reservations.json) — used to drive
# the natural availability!=booked race.
SCARCE_SLOT = "2026-07-01T19:30:00"


def _book(client: TestClient, **kwargs: object) -> dict[str, object]:
    return client.post(BOOK, headers=auth_headers(), json=booking_payload(**kwargs)).json()  # type: ignore[arg-type]


def test_book_then_cancel_lifecycle(client: TestClient) -> None:
    booked = _book(client, idempotency_key="life-1")
    cid = booked["data"]["confirmation_id"]  # type: ignore[index]

    cancelled = client.post(
        CANCEL, headers=auth_headers(), json=cancel_payload(confirmation_id=cid)
    ).json()
    assert cancelled["ok"] is True
    assert cancelled["state"] == "cancelled"


def test_cancel_is_idempotent(client: TestClient) -> None:
    cid = _book(client, idempotency_key="life-2")["data"]["confirmation_id"]  # type: ignore[index]
    first = client.post(CANCEL, headers=auth_headers(), json=cancel_payload(confirmation_id=cid))
    second = client.post(CANCEL, headers=auth_headers(), json=cancel_payload(confirmation_id=cid))
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["state"] == "cancelled"


def test_cancel_unknown_reservation_is_not_found(client: TestClient) -> None:
    resp = client.post(
        CANCEL, headers=auth_headers(), json=cancel_payload(confirmation_id="MOCK-DEMO-DOESNOTEXIST")
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_modify_unknown_reservation_is_not_found(client: TestClient) -> None:
    resp = client.post(
        MODIFY, headers=auth_headers(), json=modify_payload(confirmation_id="MOCK-DEMO-DOESNOTEXIST")
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_natural_availability_vs_booked_race(client: TestClient) -> None:
    # The scarce slot has capacity 1. First booking succeeds; the second (different
    # idempotency key) finds the slot gone -> unavailable, never a false confirmation.
    first = client.post(
        BOOK,
        headers=auth_headers(),
        json=booking_payload(idempotency_key="race-A") | {"datetime": SCARCE_SLOT},
    )
    assert first.status_code == 200 and first.json()["state"] == "confirmed"

    second = client.post(
        BOOK,
        headers=auth_headers(),
        json=booking_payload(idempotency_key="race-B") | {"datetime": SCARCE_SLOT},
    )
    assert second.status_code == 409
    assert second.json()["state"] == "unavailable"
    assert second.json()["data"] is None


def test_availability_reflects_a_booking(client: TestClient) -> None:
    # Before: the scarce slot is offered.
    before = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload()
    ).json()["data"]["slots"]
    assert any(s["time"] == SCARCE_SLOT for s in before)

    # Consume the capacity-1 scarce slot.
    client.post(
        BOOK,
        headers=auth_headers(),
        json=booking_payload(idempotency_key="reflect") | {"datetime": SCARCE_SLOT},
    )

    # After: it is no longer offered (availability reflects the booking).
    after = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload()
    ).json()["data"]["slots"]
    assert not any(s["time"] == SCARCE_SLOT for s in after)


def test_one_tenant_cannot_touch_anothers_reservation(client: TestClient) -> None:
    # demo books; acme must not be able to cancel demo's reservation (tenant-scoped).
    cid = _book(client, tenant="demo", idempotency_key="iso-1")["data"]["confirmation_id"]  # type: ignore[index]
    resp = client.post(
        CANCEL,
        headers=auth_headers(),
        json=cancel_payload(tenant="acme", confirmation_id=cid),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
