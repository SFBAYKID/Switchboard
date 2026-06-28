"""Bearer-token auth gate — 401 envelope on bad/missing token (charter Principle 5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import ENVELOPE_FIELDS, auth_headers, availability_payload

AVAIL = "/v1/reservations/availability"


def test_missing_token_returns_401_envelope(client: TestClient) -> None:
    resp = client.post(AVAIL, json=availability_payload())
    assert resp.status_code == 401
    body = resp.json()
    # Even unauthorized is a well-formed uniform envelope (not FastAPI's {"detail":…}).
    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is False
    assert body["error"]["code"] == "unauthorized"
    assert body["data"] is None
    assert body["state"] is None  # gateway-level fault, no normalized upstream state
    assert body["mock"] is False


def test_invalid_token_returns_401(client: TestClient) -> None:
    resp = client.post(AVAIL, headers=auth_headers("wrong-token"), json=availability_payload())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_malformed_authorization_header_returns_401(client: TestClient) -> None:
    resp = client.post(
        AVAIL, headers={"Authorization": "Token abc"}, json=availability_payload()
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_valid_token_succeeds(client: TestClient) -> None:
    resp = client.post(AVAIL, headers=auth_headers(), json=availability_payload())
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
