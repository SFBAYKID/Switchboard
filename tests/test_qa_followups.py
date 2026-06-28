"""Regression tests locking in QA-verified behavior (findings F3, G1, G2, G3).

These cover paths the QA pass verified by probe but the committed suite did not yet
assert: the 500 internal-error safety net + its correlation header (G1/F3), the
wall-clock "never hangs" guarantee (G2), and that latency_ms reflects real upstream
time (G3).
"""

from __future__ import annotations

import time

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


def _boom(_settings: object) -> object:
    # Simulate an UNEXPECTED (non-AppError) fault that escapes the dispatch mapping,
    # to exercise the last-resort 500 net. The message must never reach the caller.
    raise RuntimeError("internal-detail-should-never-leak")


def test_internal_error_is_uniform_envelope_no_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force a non-AppError fault in the route (before dispatch maps upstream errors).
    monkeypatch.setattr("switchboard.api.routes.reservations.select_backend", _boom)
    # raise_server_exceptions=False so TestClient returns the handled 500 response.
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(AVAIL, headers=auth_headers(), json=availability_payload())

    assert resp.status_code == 500
    body = resp.json()
    assert set(body) == set(ENVELOPE_FIELDS)
    assert body["ok"] is False
    assert body["data"] is None
    assert body["state"] is None
    assert body["error"]["code"] == "internal_error"
    # No stack trace or internal detail leaks to the caller (Rule 7 / QA).
    assert "Traceback" not in resp.text
    assert "internal-detail-should-never-leak" not in resp.text
    assert "RuntimeError" not in resp.text
    # F3: the correlation header is present even on the 500 catch-all.
    assert resp.headers["X-Request-ID"] == body["request_id"]


def test_never_hangs_on_slow_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 3s upstream with a 100ms caller deadline must return FAST, not wait 3s.
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "3000")
    reset_settings_cache()
    with TestClient(app) as c:
        started = time.perf_counter()
        resp = c.post(
            AVAIL,
            headers={**auth_headers(), "X-Deadline-Ms": "100"},
            json=availability_payload(),
        )
        wall_ms = (time.perf_counter() - started) * 1000

    assert resp.status_code == 504
    assert resp.json()["state"] == "timeout"
    # Proof it did not block on the 3s upstream (would be >=3000ms if it hung).
    assert wall_ms < 1500, f"request took {wall_ms:.0f}ms — looks like it hung"


def test_write_timeout_is_requires_human_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    # H1: a WRITE that exceeds its deadline is AMBIGUOUS (the upstream may have
    # committed). It must NOT be returned as a blindly-retryable timeout — that
    # invites a double-book. It must surface as requires_human (review #5).
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "3000")
    reset_settings_cache()
    with TestClient(app) as c:
        resp = c.post(
            BOOK,
            headers={**write_headers("wt-1"), "X-Deadline-Ms": "100"},
            json=booking_payload(),
        )

    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "requires_human"
    assert body["error"]["retryable"] is False
    assert body["data"] is None  # never a (false) confirmation


def test_latency_ms_reflects_upstream_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    # latency_ms must be MEASURED, not a placeholder: a ~200ms upstream shows up.
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "200")
    reset_settings_cache()
    with TestClient(app) as c:
        body = c.post(AVAIL, headers=auth_headers(), json=availability_payload()).json()

    assert body["ok"] is True
    assert body["latency_ms"] >= 150  # reflects the injected delay, not 0
