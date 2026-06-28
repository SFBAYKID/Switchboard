"""Hostile mock outcomes — normalized states, never a leaked error or false success.

Review #2/#3/#5/#7: the mock injects the conditions real life produces, and every one
resolves to exactly one normalized state via the uniform envelope — never a raw vendor
error, never a false confirmation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from switchboard.api.main import app
from switchboard.core.config import reset_settings_cache
from tests.helpers import (
    ENVELOPE_FIELDS,
    auth_headers,
    availability_payload,
    booking_payload,
    write_headers,
)

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"


def _client_with(monkeypatch: pytest.MonkeyPatch, *, fail: str) -> TestClient:
    monkeypatch.setenv("MOCK_RESERVATIONS_FAIL", fail)
    reset_settings_cache()
    return TestClient(app)


@pytest.mark.parametrize(
    "fail_mode,state,code,status,retryable",
    [
        ("auth_error", "auth_error", "auth_error", 502, False),
        ("rate_limited", "rate_limited", "rate_limited", 429, True),
        ("unknown", "unknown", "unknown", 502, True),
    ],
)
def test_availability_hostile_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    fail_mode: str,
    state: str,
    code: str,
    status: int,
    retryable: bool,
) -> None:
    with _client_with(monkeypatch, fail=fail_mode) as c:
        resp = c.post(AVAIL, headers=auth_headers(), json=availability_payload())

    assert resp.status_code == status
    body = resp.json()
    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is False
    assert body["data"] is None  # never a payload on a failure
    assert body["state"] == state
    assert body["error"]["code"] == code
    assert body["error"]["retryable"] is retryable
    assert body["mock"] is True
    assert body["source"] == "reservations"


def test_book_requires_human_on_ambiguous_race(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review #5: ambiguous booking outcome -> requires_human, NEVER a false confirmation.
    with _client_with(monkeypatch, fail="booking_race") as c:
        resp = c.post(BOOK, headers=write_headers("race-1"), json=booking_payload())

    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "requires_human"
    assert body["data"] is None  # no confirmation id on an ambiguous outcome
    assert body["error"]["retryable"] is False


def test_book_unavailable_when_slot_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    # Review #5: the availability != booked race, slot gone -> unavailable, no booking.
    with _client_with(monkeypatch, fail="slot_gone") as c:
        resp = c.post(BOOK, headers=write_headers("slot-1"), json=booking_payload())

    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "unavailable"
    assert body["data"] is None


def test_opentable_seam_surfaces_safe_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    # Selecting the not-yet-built real backend must surface a SAFE normalized outcome
    # (unknown), not a leaked NotImplementedError/stack trace; and mock must be false.
    monkeypatch.setenv("RESERVATIONS_BACKEND", "opentable")
    reset_settings_cache()
    with TestClient(app) as c:
        resp = c.post(AVAIL, headers=auth_headers(), json=availability_payload())

    assert resp.status_code == 502
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "unknown"
    assert body["mock"] is False
    # The raw NotImplementedError text must never reach the caller.
    assert "NotImplementedError" not in resp.text
    assert "Traceback" not in resp.text
