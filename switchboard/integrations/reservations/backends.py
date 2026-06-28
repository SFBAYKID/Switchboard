"""Reservations backend selection — config, not code (architecture.md).

Deliberately thin (review #1: "do NOT build a plugin/registry framework"). This is a
single function that picks ONE of this integration's two concrete backends based on
config (`RESERVATIONS_BACKEND = "mock" | "opentable"`). It is NOT a generic
cross-integration dispatcher — each future integration ships its OWN
capability-shaped endpoints and its OWN small selector like this one.

The API layer calls `select_backend(settings)` and receives something typed as the
`ReservationsBackend` Protocol — it never names a concrete vendor class.
"""

from __future__ import annotations

from switchboard.core.config import Settings
from switchboard.integrations.reservations.backend_mock import MockReservationsBackend
from switchboard.integrations.reservations.backend_opentable import (
    OpenTableReservationsBackend,
)
from switchboard.integrations.reservations.interface import ReservationsBackend
from switchboard.integrations.reservations.mock_store import get_store


def select_backend(settings: Settings) -> ReservationsBackend:
    """Return the configured reservations backend (mock or the OpenTable seam)."""

    if settings.reservations_backend == "mock":
        return MockReservationsBackend(
            get_store(settings.mock_reservations_seed_path),
            delay_ms=settings.mock_reservations_delay_ms,
            fail_mode=settings.mock_reservations_fail,
        )
    if settings.reservations_backend == "opentable":
        # SEAM: constructs fine; calling it raises NotImplementedError until the real
        # client is written (post-approval, docs-verified — Rule 2). The dispatch
        # layer surfaces that as a safe `unknown` outcome rather than a leaked trace.
        return OpenTableReservationsBackend()
    # Unreachable: the Literal type + config validation constrain the value. Kept as
    # a defensive fail-loud guard.
    raise ValueError(
        f"Unknown RESERVATIONS_BACKEND: {settings.reservations_backend!r}"
    )


def is_mock(settings: Settings) -> bool:
    """Whether the active reservations backend is a mock (for the envelope flag)."""

    return settings.reservations_backend == "mock"
