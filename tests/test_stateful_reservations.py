"""Stateful dummy-data behavior: lifecycle, the natural race, and restaurant isolation.

These exercise the JSON-seeded stateful mock store end-to-end through the API — the
behavior the calling agent (nico) will rely on while testing its integration during
the OpenTable approval wait. Verified-on-mock.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import (
    SCARCE_TIME,
    auth_headers,
    availability_payload,
    booking_payload,
    cancel_payload,
    modify_payload,
    write_headers,
)

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"
MODIFY = "/v1/reservations/modify"
CANCEL = "/v1/reservations/cancel"


def test_book_then_cancel_lifecycle(client: TestClient) -> None:
    cid = client.post(
        BOOK, headers=write_headers("life-1"), json=booking_payload()
    ).json()["data"]["confirmation_id"]

    cancelled = client.post(
        CANCEL, headers=write_headers("life-1-cancel"), json=cancel_payload(confirmation_id=cid)
    ).json()
    assert cancelled["ok"] is True
    assert cancelled["state"] == "cancelled"


def test_cancel_is_idempotent(client: TestClient) -> None:
    cid = client.post(
        BOOK, headers=write_headers("life-2"), json=booking_payload()
    ).json()["data"]["confirmation_id"]
    first = client.post(CANCEL, headers=write_headers("c-a"), json=cancel_payload(confirmation_id=cid))
    second = client.post(CANCEL, headers=write_headers("c-b"), json=cancel_payload(confirmation_id=cid))
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["state"] == "cancelled"


def test_cancel_unknown_reservation_is_not_found(client: TestClient) -> None:
    resp = client.post(
        CANCEL,
        headers=write_headers("c-unknown"),
        json=cancel_payload(confirmation_id="MOCK-DEMO-DOESNOTEXIST"),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_modify_unknown_reservation_is_not_found(client: TestClient) -> None:
    resp = client.post(
        MODIFY,
        headers=write_headers("m-unknown"),
        json=modify_payload(confirmation_id="MOCK-DEMO-DOESNOTEXIST"),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_natural_availability_vs_booked_race(client: TestClient) -> None:
    # The scarce slot has capacity 1. First booking succeeds; the second (different
    # idempotency key) finds the slot gone -> unavailable, never a false confirmation.
    first = client.post(
        BOOK, headers=write_headers("race-A"), json=booking_payload(time=SCARCE_TIME)
    )
    assert first.status_code == 200 and first.json()["state"] == "confirmed"

    second = client.post(
        BOOK, headers=write_headers("race-B"), json=booking_payload(time=SCARCE_TIME)
    )
    assert second.status_code == 409
    assert second.json()["state"] == "unavailable"
    assert second.json()["data"] is None


def test_availability_reflects_a_booking(client: TestClient) -> None:
    # Before: the scarce slot is offered.
    before = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(time=SCARCE_TIME)
    ).json()["data"]["slots"]
    assert any(s["time"] == SCARCE_TIME for s in before)

    # Consume the capacity-1 scarce slot.
    client.post(BOOK, headers=write_headers("reflect"), json=booking_payload(time=SCARCE_TIME))

    # After: it is no longer offered (availability reflects the booking).
    after = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(time=SCARCE_TIME)
    ).json()["data"]["slots"]
    assert not any(s["time"] == SCARCE_TIME for s in after)


def test_one_restaurant_cannot_touch_anothers_reservation(client: TestClient) -> None:
    # demo books; acme must not be able to cancel demo's reservation (scoped).
    cid = client.post(
        BOOK, headers=write_headers("iso-1"), json=booking_payload(restaurant_id="demo")
    ).json()["data"]["confirmation_id"]
    resp = client.post(
        CANCEL,
        headers=write_headers("iso-1-x"),
        json=cancel_payload(restaurant_id="acme", confirmation_id=cid),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
