"""Switchboard configuration — validated at startup, fails loudly (Rule 7).

All of Switchboard's tunables come from its OWN environment (its OWN `.env` in dev,
the process environment in any deploy). `Settings` is a pydantic-settings model so:
  - required vars that are missing raise a clear `ValidationError` NAMING the var,
  - constraints are enforced (e.g. the deadline safety margin must be below the
    per-endpoint budgets, or the budget guarantee is a lie),
  - mock mode is refused in production unless an explicit flag is set (review #7),
  - nothing is silently defaulted that must be set deliberately.

Secrets handling: `SWITCHBOARD_API_TOKEN` and the per-tenant upstream credentials
live in the environment only. They are NEVER logged or printed, and the whole
settings object is never dumped to logs (Rule 7).

Per-tenant upstream credentials are NOT modeled as fixed fields here — tenant names
are dynamic (`SWITCHBOARD_OPENTABLE__<TENANT>__API_KEY`), so they are read on demand
by `core.credentials`. This module owns the static, known-ahead-of-time config.

dotenv: in dev we load Switchboard's OWN `.env` into the process environment (so the
credential resolver, which reads `os.environ`, sees the same values pydantic does).
Tests set `SWITCHBOARD_DISABLE_DOTENV=1` to stay fully hermetic (no real `.env`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Deployment environment. Mock mode is refused in production unless explicitly
# allowed (review #7). Default development so local dev "just works".
Environment = Literal["development", "production"]

# Backend selection for the reservations integration. "mock" is the default until
# real OpenTable partner approval lands; "opentable" is the go-live flip.
ReservationsBackendName = Literal["mock", "opentable"]

# Mock failure-injection mode (mock backend only). Hostile-by-design (review #7).
# See switchboard.integrations.reservations.backend_mock for behavior.
MockFailMode = Literal[
    "none",
    "auth_error",
    "rate_limited",
    "unknown",
    "booking_race",  # book(): ambiguous race -> requires_human
    "slot_gone",  # book(): slot vanished -> unavailable
]


class Settings(BaseSettings):
    """Static, validated configuration for the Switchboard service."""

    model_config = SettingsConfigDict(
        extra="ignore",  # ignore unrelated env vars (incl. the dynamic tenant creds)
        case_sensitive=False,
    )

    # ── Deployment environment + mock safety (review #7) ──────────────────────
    environment: Environment = Field(
        default="development",
        validation_alias="SWITCHBOARD_ENV",
    )
    allow_mock_in_prod: bool = Field(
        default=False,
        validation_alias="SWITCHBOARD_ALLOW_MOCK_IN_PROD",
    )

    # ── Internal API auth (REQUIRED) ──────────────────────────────────────────
    # The bearer token gating every internal request. Required, min length 8 so a
    # blank/trivial token is rejected loudly at startup. (Per-caller tokens are a
    # planned extension; one shared token for the MVP.)
    api_token: str = Field(
        min_length=8,
        validation_alias="SWITCHBOARD_API_TOKEN",
    )

    # ── Reservations backend selection ────────────────────────────────────────
    reservations_backend: ReservationsBackendName = Field(
        default="mock",
        validation_alias="RESERVATIONS_BACKEND",
    )

    # ── Per-endpoint latency budgets (review #4) ──────────────────────────────
    # Budgets are PER-ENDPOINT, not one flat number. The effective deadline for a
    # request is min(endpoint budget, caller-supplied X-Deadline-Ms). Switchboard
    # answers within that budget — with the result OR a clean `timeout` outcome.
    availability_budget_ms: int = Field(
        default=1500,
        gt=0,
        validation_alias="SWITCHBOARD_AVAILABILITY_BUDGET_MS",
    )
    booking_budget_ms: int = Field(
        default=1500,
        gt=0,
        validation_alias="SWITCHBOARD_BOOKING_BUDGET_MS",
    )
    # Margin subtracted from the budget to leave room to build/return the envelope
    # WITHIN the budget (so a budget-tripping upstream still answers in time).
    budget_safety_margin_ms: int = Field(
        default=50,
        ge=0,
        validation_alias="SWITCHBOARD_BUDGET_SAFETY_MARGIN_MS",
    )

    # ── Mock backend behavior knobs (mock mode only; hostile-by-design) ───────
    mock_reservations_delay_ms: int = Field(
        default=0,
        ge=0,
        validation_alias="MOCK_RESERVATIONS_DELAY_MS",
    )
    mock_reservations_fail: MockFailMode = Field(
        default="none",
        validation_alias="MOCK_RESERVATIONS_FAIL",
    )
    # Path to the JSON seed for the stateful mock store. None -> bundled default
    # (data/mock_reservations.json).
    mock_reservations_seed_path: str | None = Field(
        default=None,
        validation_alias="MOCK_RESERVATIONS_SEED_PATH",
    )

    @model_validator(mode="after")
    def _margin_below_budgets(self) -> "Settings":
        """The safety margin must be strictly below every per-endpoint budget.

        Otherwise the effective upstream timeout could collapse to ~0 and every call
        would spuriously time out. Fail loudly at startup if misconfigured.
        """

        smallest_budget = min(self.availability_budget_ms, self.booking_budget_ms)
        if self.budget_safety_margin_ms >= smallest_budget:
            raise ValueError(
                "SWITCHBOARD_BUDGET_SAFETY_MARGIN_MS "
                f"({self.budget_safety_margin_ms}) must be strictly less than every "
                f"per-endpoint budget (smallest is {smallest_budget}ms)."
            )
        return self

    @model_validator(mode="after")
    def _no_mock_in_prod_without_flag(self) -> "Settings":
        """Refuse mock mode in production unless explicitly allowed (review #7).

        Mock mode returns fabricated data; silently serving it in production would be
        dangerous. It is allowed in production ONLY with an explicit opt-in flag, so
        it can never be used in prod by accident.
        """

        if (
            self.environment == "production"
            and self.reservations_backend == "mock"
            and not self.allow_mock_in_prod
        ):
            raise ValueError(
                "RESERVATIONS_BACKEND=mock is refused while SWITCHBOARD_ENV=production. "
                "Mock mode returns fabricated data. Set RESERVATIONS_BACKEND=opentable, "
                "or, only if you truly intend to serve mock data in production, set "
                "SWITCHBOARD_ALLOW_MOCK_IN_PROD=true."
            )
        return self


def _dotenv_enabled() -> bool:
    """Whether to load Switchboard's OWN `.env`. Tests disable this for hermeticity."""

    return os.environ.get("SWITCHBOARD_DISABLE_DOTENV") != "1"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the validated settings singleton (cached).

    On first call in dev, loads Switchboard's OWN `.env` into the process
    environment (override=False, so a real environment var always wins) so the
    credential resolver — which reads `os.environ` directly for the dynamic
    per-tenant keys — sees the same values. Raises a clear `ValidationError` if a
    required var is missing or invalid (fail loud, Rule 7).
    """

    if _dotenv_enabled():
        load_dotenv(".env", override=False)
    # Values come from the environment (validation aliases), not constructor kwargs.
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (tests call this after mutating the environment)."""

    get_settings.cache_clear()
