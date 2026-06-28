"""Deadline propagation + per-endpoint budgets (review #4).

The effective deadline is min(per-endpoint budget, caller X-Deadline-Ms) minus the
safety margin; an upstream that exceeds it yields a clean `timeout` within budget —
the gateway never hangs the caller.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from switchboard.api.main import app
from switchboard.core.config import reset_settings_cache
from tests.helpers import auth_headers, availability_payload

AVAIL = "/v1/reservations/availability"


def test_caller_deadline_triggers_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Upstream takes 300ms; caller's hard deadline is 100ms -> timeout, fast.
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "300")
    reset_settings_cache()
    with TestClient(app) as c:
        resp = c.post(
            AVAIL,
            headers={**auth_headers(), "X-Deadline-Ms": "100"},
            json=availability_payload(),
        )

    assert resp.status_code == 504
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "timeout"
    assert body["error"]["code"] == "timeout"
    assert body["error"]["retryable"] is True
    # Answered within budget (nowhere near the 300ms upstream, never hung).
    assert body["latency_ms"] < 1500


def test_per_endpoint_budget_triggers_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # No caller deadline; the per-endpoint budget (120ms) bounds a 300ms upstream.
    monkeypatch.setenv("SWITCHBOARD_AVAILABILITY_BUDGET_MS", "120")
    monkeypatch.setenv("SWITCHBOARD_BUDGET_SAFETY_MARGIN_MS", "20")
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "300")
    reset_settings_cache()
    with TestClient(app) as c:
        resp = c.post(AVAIL, headers=auth_headers(), json=availability_payload())

    assert resp.status_code == 504
    assert resp.json()["state"] == "timeout"


def test_generous_deadline_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # A small upstream delay well under a generous deadline returns a real answer.
    monkeypatch.setenv("MOCK_RESERVATIONS_DELAY_MS", "20")
    reset_settings_cache()
    with TestClient(app) as c:
        resp = c.post(
            AVAIL,
            headers={**auth_headers(), "X-Deadline-Ms": "1000"},
            json=availability_payload(),
        )

    assert resp.status_code == 200
    assert resp.json()["state"] == "available"
