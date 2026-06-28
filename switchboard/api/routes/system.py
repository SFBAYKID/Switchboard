"""System endpoints — liveness and version/contract info (no auth, no secrets).

These are operational, not capability, endpoints, so they are NOT token-gated and
carry no normalized `state` (state is for real-time capability outcomes). They never
return secrets (architecture.md: `/healthz` "returns no secrets").

  - GET /healthz — canonical liveness/readiness probe (architecture.md).
  - GET /health  — alias of /healthz for the documented Postman/Newman CI healthcheck
                   (postman-setup.md polls `/health`). Same handler; kept so the docs'
                   CI flow works without ambiguity.
  - GET /v1      — contract/version info: name, version, which integrations are live.

Note: these responses are plain JSON, not the uniform capability envelope — they are
infrastructure probes, not integration calls. The `X-Request-ID` correlation header
is still applied by the timing middleware.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from switchboard import __version__

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Liveness payload — intentionally tiny and secret-free."""

    status: str
    version: str


class VersionInfo(BaseModel):
    """Contract/version info for the internal API."""

    name: str
    api_version: str
    version: str
    integrations: list[str]


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Return liveness. No auth, no secrets."""

    return HealthResponse(status="ok", version=__version__)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe (alias)")
async def health() -> HealthResponse:
    """Alias of /healthz for the documented Postman/CI healthcheck."""

    return HealthResponse(status="ok", version=__version__)


@router.get("/v1", response_model=VersionInfo, summary="Contract/version info")
async def version_info() -> VersionInfo:
    """Return the internal API's name, version, and live integrations."""

    return VersionInfo(
        name="Switchboard",
        api_version="v1",
        version=__version__,
        # Only BUILT integrations are listed (reservations). payments/website are
        # clearly-marked future seams and are intentionally absent.
        integrations=["reservations"],
    )
