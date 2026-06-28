"""Correlation IDs threading caller + gateway (review #6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import auth_headers, availability_payload

AVAIL = "/v1/reservations/availability"


def test_request_id_generated_and_echoed(client: TestClient) -> None:
    resp = client.post(AVAIL, headers=auth_headers(), json=availability_payload())
    body = resp.json()
    assert body["request_id"]
    # The envelope's request_id matches the response header.
    assert resp.headers["X-Request-ID"] == body["request_id"]


def test_inbound_request_id_is_honored(client: TestClient) -> None:
    rid = "trace-abc-123"
    resp = client.post(
        AVAIL,
        headers={**auth_headers(), "X-Request-ID": rid},
        json=availability_payload(),
    )
    body = resp.json()
    assert body["request_id"] == rid
    assert resp.headers["X-Request-ID"] == rid


def test_unsafe_inbound_request_id_is_replaced(client: TestClient) -> None:
    # An unsafe inbound id (spaces) is rejected; the gateway mints its own.
    resp = client.post(
        AVAIL,
        headers={**auth_headers(), "X-Request-ID": "bad id with spaces"},
        json=availability_payload(),
    )
    body = resp.json()
    assert body["request_id"] != "bad id with spaces"
    assert resp.headers["X-Request-ID"] == body["request_id"]


def test_request_id_present_on_error_too(client: TestClient) -> None:
    resp = client.post(AVAIL, json=availability_payload())  # missing auth -> 401
    assert resp.status_code == 401
    body = resp.json()
    assert body["request_id"]
    assert resp.headers["X-Request-ID"] == body["request_id"]
