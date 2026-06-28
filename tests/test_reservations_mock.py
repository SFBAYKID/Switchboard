"""Reservations mock backend — data shapes + idempotency (the happy paths)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import (
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


def test_availability_available_returns_slots(client: TestClient) -> None:
    body = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(party_size=2)
    ).json()
    assert body["ok"] is True
    assert body["state"] == "available"
    slots = body["data"]["slots"]
    assert len(slots) > 0
    for slot in slots:
        assert "date" in slot and "time" in slot and "party_size" in slot


def test_availability_unavailable_for_large_party(client: TestClient) -> None:
    body = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(party_size=20)
    ).json()
    assert body["ok"] is True  # answering "no availability" is a definitive success
    assert body["state"] == "unavailable"
    assert body["data"]["slots"] == []


def test_book_returns_confirmation(client: TestClient) -> None:
    body = client.post(
        BOOK, headers=write_headers("book-1"), json=booking_payload()
    ).json()
    assert body["ok"] is True
    assert body["state"] == "confirmed"
    assert body["data"]["confirmation_id"].startswith("MOCK-DEMO-")


def test_book_idempotent_same_key_same_confirmation(client: TestClient) -> None:
    # A retried booking with the same Idempotency-Key must NOT double-book.
    first = client.post(BOOK, headers=write_headers("idem-key-1"), json=booking_payload()).json()
    second = client.post(BOOK, headers=write_headers("idem-key-1"), json=booking_payload()).json()
    assert first["data"]["confirmation_id"] == second["data"]["confirmation_id"]


def test_book_different_key_different_confirmation(client: TestClient) -> None:
    one = client.post(BOOK, headers=write_headers("k1"), json=booking_payload()).json()
    two = client.post(BOOK, headers=write_headers("k2"), json=booking_payload()).json()
    assert one["data"]["confirmation_id"] != two["data"]["confirmation_id"]


def test_modify_existing_reservation(client: TestClient) -> None:
    # The stateful store requires a real reservation, so book first.
    cid = client.post(
        BOOK, headers=write_headers("modify-me"), json=booking_payload()
    ).json()["data"]["confirmation_id"]

    body = client.post(
        MODIFY, headers=write_headers("modify-1"), json=modify_payload(confirmation_id=cid)
    ).json()
    assert body["ok"] is True
    assert body["state"] == "modified"
    assert body["data"]["confirmation_id"] == cid


def test_cancel_existing_reservation(client: TestClient) -> None:
    cid = client.post(
        BOOK, headers=write_headers("cancel-me"), json=booking_payload()
    ).json()["data"]["confirmation_id"]

    body = client.post(
        CANCEL, headers=write_headers("cancel-1"), json=cancel_payload(confirmation_id=cid)
    ).json()
    assert body["ok"] is True
    assert body["state"] == "cancelled"
    assert body["data"]["confirmation_id"] == cid


def test_write_requires_idempotency_key_header(client: TestClient) -> None:
    # Review #5: writes REQUIRE the Idempotency-Key header — omitting it is a 400.
    resp = client.post(BOOK, headers=auth_headers(), json=booking_payload())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"
