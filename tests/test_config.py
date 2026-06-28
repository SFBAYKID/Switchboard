"""Config validation — fails loudly on misconfiguration (Rule 7, review #7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from switchboard.api.main import app
from switchboard.core.config import get_settings, reset_settings_cache


def test_missing_token_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SWITCHBOARD_API_TOKEN", raising=False)
    reset_settings_cache()
    with pytest.raises(ValidationError) as ei:
        get_settings()
    # Must NAME the missing var so the operator knows what to set.
    assert "SWITCHBOARD_API_TOKEN" in str(ei.value)


def test_short_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHBOARD_API_TOKEN", "short")  # < 8 chars
    reset_settings_cache()
    with pytest.raises(ValidationError):
        get_settings()


def test_mock_in_prod_refused_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHBOARD_ENV", "production")
    monkeypatch.setenv("RESERVATIONS_BACKEND", "mock")
    monkeypatch.delenv("SWITCHBOARD_ALLOW_MOCK_IN_PROD", raising=False)
    reset_settings_cache()
    with pytest.raises(ValidationError) as ei:
        get_settings()
    assert "SWITCHBOARD_ALLOW_MOCK_IN_PROD" in str(ei.value)


def test_mock_in_prod_allowed_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHBOARD_ENV", "production")
    monkeypatch.setenv("RESERVATIONS_BACKEND", "mock")
    monkeypatch.setenv("SWITCHBOARD_ALLOW_MOCK_IN_PROD", "true")
    reset_settings_cache()
    settings = get_settings()
    assert settings.environment == "production"
    assert settings.reservations_backend == "mock"
    assert settings.allow_mock_in_prod is True


def test_margin_must_be_below_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SWITCHBOARD_AVAILABILITY_BUDGET_MS", "100")
    monkeypatch.setenv("SWITCHBOARD_BUDGET_SAFETY_MARGIN_MS", "100")
    reset_settings_cache()
    with pytest.raises(ValidationError) as ei:
        get_settings()
    assert "MARGIN" in str(ei.value).upper()


def test_valid_config_loads() -> None:
    settings = get_settings()
    assert settings.api_token  # present (hermetic env sets it)
    assert settings.reservations_backend == "mock"
    assert settings.availability_budget_ms == 1500
    assert settings.environment == "development"


def test_zero_tenant_startup_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Remove all configured tenants -> the service must refuse to start (loud).
    monkeypatch.delenv("SWITCHBOARD_OPENTABLE__DEMO__API_KEY", raising=False)
    monkeypatch.delenv("SWITCHBOARD_OPENTABLE__ACME__API_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(RuntimeError) as ei:
        with TestClient(app):
            pass
    assert "API_KEY" in str(ei.value)
