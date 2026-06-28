"""Reservations mock backend — data shapes + idempotency (the happy paths)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import WHEN, auth_headers, availability_payload, booking_payload

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
        assert "time" in slot and "party_size" in slot


def test_availability_unavailable_for_large_party(client: TestClient) -> None:
    body = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(party_size=20)
    ).json()
    assert body["ok"] is True  # answering "no availability" is a definitive success
    assert body["state"] == "unavailable"
    assert body["data"]["slots"] == []


def test_book_returns_confirmation(client: TestClient) -> None:
    body = client.post(BOOK, headers=auth_headers(), json=booking_payload()).json()
    assert body["ok"] is True
    assert body["state"] == "confirmed"
    assert body["data"]["confirmation_id"].startswith("MOCK-DEMO-")


def test_book_idempotent_same_key_same_confirmation(client: TestClient) -> None:
    payload = booking_payload(idempotency_key="idem-key-1")
    first = client.post(BOOK, headers=auth_headers(), json=payload).json()
    second = client.post(BOOK, headers=auth_headers(), json=payload).json()
    # A retried booking with the same idempotency key must NOT double-book.
    assert first["data"]["confirmation_id"] == second["data"]["confirmation_id"]


def test_book_different_key_different_confirmation(client: TestClient) -> None:
    one = client.post(
        BOOK, headers=auth_headers(), json=booking_payload(idempotency_key="k1")
    ).json()
    two = client.post(
        BOOK, headers=auth_headers(), json=booking_payload(idempotency_key="k2")
    ).json()
    assert one["data"]["confirmation_id"] != two["data"]["confirmation_id"]


def test_modify_echoes_confirmation(client: TestClient) -> None:
    body = client.post(
        MODIFY,
        headers=auth_headers(),
        json={"tenant": "demo", "confirmation_id": "MOCK-DEMO-ABC123", "datetime": WHEN},
    ).json()
    assert body["ok"] is True
    assert body["state"] == "modified"
    assert body["data"]["confirmation_id"] == "MOCK-DEMO-ABC123"


def test_cancel_echoes_confirmation(client: TestClient) -> None:
    body = client.post(
        CANCEL,
        headers=auth_headers(),
        json={"tenant": "demo", "confirmation_id": "MOCK-DEMO-ABC123"},
    ).json()
    assert body["ok"] is True
    assert body["state"] == "cancelled"
    assert body["data"]["confirmation_id"] == "MOCK-DEMO-ABC123"
