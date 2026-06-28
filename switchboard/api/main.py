"""Switchboard FastAPI application factory + ASGI entrypoint.

Run (dev):  uvicorn switchboard.api.main:app --host 127.0.0.1 --port 8080
(Bind to 127.0.0.1 — internal-only; review #8 "decouple logically, not physically".)

Startup (lifespan) validates configuration and FAILS LOUDLY (Rule 7) before serving:
  - `get_settings()` raises if a required var is missing, the deadline margin is
    not below the budgets, or mock mode is selected in production without the
    explicit flag (review #7).
  - At least one per-tenant reservations credential must be configured, else the
    service refuses to start (a zero-tenant gateway is a misconfiguration).

The factory wires: the timing + correlation-id middleware, the three exception
handlers (uniform error envelope on every failure), and the capability/system
routers. No secrets are logged.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from switchboard import __version__
from switchboard.api.error_handlers import register_exception_handlers
from switchboard.api.routes import reservations, system
from switchboard.api.timing import timing_middleware
from switchboard.core.config import Settings, get_settings
from switchboard.core.credentials import configured_tenants
from switchboard.integrations.reservations import CREDENTIAL_NAMESPACE

logger = logging.getLogger("switchboard")

_DESCRIPTION = (
    "Switchboard — the Integration Gateway. A standalone, internal-only HTTP API "
    "that owns third-party integrations behind one clean, versioned, token-gated "
    "contract and returns a uniform response envelope with a normalized result "
    "state. Reservations (OpenTable) is the first integration, mock-first."
)


def _validate_startup(settings: Settings) -> None:
    """Fail loudly if the gateway cannot serve correctly (Rule 7)."""

    tenants = configured_tenants(CREDENTIAL_NAMESPACE)
    if not tenants:
        raise RuntimeError(
            "No reservations tenant credentials are configured. Set at least one "
            f"SWITCHBOARD_{CREDENTIAL_NAMESPACE}__<TENANT>__API_KEY before starting."
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate config at startup; refuse to serve if misconfigured."""

    settings = get_settings()  # fail loud on missing/invalid required config
    _validate_startup(settings)
    # Secret-free startup line: never log the token or credentials.
    logger.info(
        "Switchboard %s starting: env=%s reservations_backend=%s tenants=%d",
        __version__,
        settings.environment,
        settings.reservations_backend,
        len(configured_tenants(CREDENTIAL_NAMESPACE)),
    )
    yield


def create_app() -> FastAPI:
    """Build and configure the Switchboard FastAPI app."""

    app = FastAPI(
        title="Switchboard — Integration Gateway",
        version=__version__,
        description=_DESCRIPTION,
        lifespan=lifespan,
    )

    # Cross-cutting: timing + correlation id on every request (review #6, Rule 5).
    app.middleware("http")(timing_middleware)

    # Uniform error envelope on every failure path.
    register_exception_handlers(app)

    # Routers. System (health/version) is unauthenticated; reservations is gated.
    app.include_router(system.router)
    app.include_router(reservations.router)

    return app


# The ASGI app object uvicorn serves.
app = create_app()
