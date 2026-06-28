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
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

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


# The internal bearer-token security scheme advertised in the contract (F2). The
# gate is enforced at runtime by `api.auth.require_bearer_token`; this makes the
# requirement visible to anyone generating a client from the spec.
_BEARER_SCHEME_NAME = "BearerAuth"


def _build_openapi(app: FastAPI) -> dict[str, Any]:
    """Generate the OpenAPI schema, correcting it to match the real contract.

    Two corrections so the published spec does not lie about the running service
    (charter Principle 1):
      - Strip the auto `422` response: validation failures are returned as `400` +
        the uniform envelope (see the validation handler), never a 422.
      - Declare the bearer-token security scheme and require it on the gated
        `/v1/reservations/*` routes (the system endpoints stay open).
    """

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})[_BEARER_SCHEME_NAME] = {
        "type": "http",
        "scheme": "bearer",
        "description": "Switchboard's internal bearer token (Authorization: Bearer <token>).",
    }

    for path, path_item in schema.get("paths", {}).items():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue  # skip path-item-level "parameters"/"summary"/etc.
            operation.get("responses", {}).pop("422", None)
            if path.startswith("/v1/reservations"):
                operation["security"] = [{_BEARER_SCHEME_NAME: []}]

    return schema


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

    # Custom OpenAPI so the published contract matches the running service (F1/F2):
    # accurate error responses (declared per-route), no spurious 422, bearer security.
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _build_openapi(app)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app


# The ASGI app object uvicorn serves.
app = create_app()
