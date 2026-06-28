"""Uniform envelope shape + invariants on success AND failure (architecture.md)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import ENVELOPE_FIELDS, auth_headers, availability_payload

AVAIL = "/v1/reservations/availability"


def test_success_envelope_shape_and_invariants(client: TestClient) -> None:
    body = client.post(AVAIL, headers=auth_headers(), json=availability_payload()).json()

    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is True
    assert body["error"] is None  # ok=true => error null
    assert body["data"] is not None  # ok=true => data present
    assert body["source"] == "reservations"
    assert body["mock"] is True
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert body["state"] in {"available", "unavailable"}
    assert isinstance(body["request_id"], str) and body["request_id"]


def test_error_envelope_shape_matches_success(client: TestClient) -> None:
    # Unknown tenant => ok=false path (fail closed).
    resp = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(tenant="ghosttenant")
    )
    assert resp.status_code == 404
    body = resp.json()

    # The error envelope has the EXACT same top-level field set as success.
    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is False
    assert body["data"] is None  # ok=false => data null
    assert body["error"] is not None
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["retryable"], bool)
    assert isinstance(body["request_id"], str) and body["request_id"]


def test_bad_request_is_uniform_envelope(client: TestClient) -> None:
    # party_size 0 is invalid -> bad_request envelope, not a raw 422 {"detail":…}.
    resp = client.post(
        AVAIL,
        headers=auth_headers(),
        json={"tenant": "demo", "party_size": 0, "datetime": "2026-07-01T19:00:00"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_request"
    assert body["state"] is None
