"""Pytest fixtures — a hermetic environment + a TestClient.

Every test runs against a fully hermetic environment (SWITCHBOARD_DISABLE_DOTENV=1, so
the real .env is never read) with a known token and two configured tenants. The
settings cache is reset around every test so env changes a test makes take effect.

Tests that mutate the environment (delay/fail injection, prod mode, missing vars)
should set their env vars, call `reset_settings_cache()`, then build a fresh
`TestClient(app)` inside the test (NOT use the `client` fixture, which is created
before the test body runs). The `client` fixture is for tests that use the default
hermetic env as-is.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from switchboard.api.main import app
from switchboard.core.config import reset_settings_cache
from switchboard.integrations.reservations.mock_store import reset_store
from tests.helpers import ACME_KEY, ACME_RID, DEMO_KEY, DEMO_RID, TEST_TOKEN


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set a known, isolated environment for every test; reset the settings cache."""

    monkeypatch.setenv("SWITCHBOARD_DISABLE_DOTENV", "1")  # never read the real .env
    monkeypatch.setenv("SWITCHBOARD_ENV", "development")
    monkeypatch.setenv("SWITCHBOARD_API_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("RESERVATIONS_BACKEND", "mock")
    monkeypatch.setenv("SWITCHBOARD_OPENTABLE__DEMO__API_KEY", DEMO_KEY)
    monkeypatch.setenv("SWITCHBOARD_OPENTABLE__DEMO__RID", DEMO_RID)
    monkeypatch.setenv("SWITCHBOARD_OPENTABLE__ACME__API_KEY", ACME_KEY)
    monkeypatch.setenv("SWITCHBOARD_OPENTABLE__ACME__RID", ACME_RID)
    monkeypatch.setenv("SWITCHBOARD_AVAILABILITY_BUDGET_MS", "1500")
    monkeypatch.setenv("SWITCHBOARD_BOOKING_BUDGET_MS", "1500")
    monkeypatch.setenv("SWITCHBOARD_BUDGET_SAFETY_MARGIN_MS", "50")
    # Ensure no stray injection knobs leak in from the ambient environment.
    monkeypatch.delenv("MOCK_RESERVATIONS_DELAY_MS", raising=False)
    monkeypatch.delenv("MOCK_RESERVATIONS_FAIL", raising=False)
    monkeypatch.delenv("MOCK_RESERVATIONS_SEED_PATH", raising=False)
    monkeypatch.delenv("SWITCHBOARD_ALLOW_MOCK_IN_PROD", raising=False)

    reset_settings_cache()
    reset_store()  # stateful mock store back to its JSON seed for test isolation
    yield
    reset_settings_cache()
    reset_store()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient over the app (runs lifespan startup validation) for the default env."""

    with TestClient(app) as test_client:
        yield test_client
