"""Shared test constants + helpers.

These are TEST values only — Switchboard's real secrets live in its gitignored .env
and are never used here. The suite is fully hermetic (SWITCHBOARD_DISABLE_DOTENV=1),
so it never reads the real .env.
"""

from __future__ import annotations

# The uniform envelope's exact field set — asserted identical on success AND error.
ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {"ok", "state", "data", "error", "source", "latency_ms", "mock", "request_id"}
)

# Test bearer token + two distinct tenant credentials (for isolation tests). The two
# api-key VALUES are deliberately distinct strings so a leak/cross-bleed is detectable.
TEST_TOKEN: str = "test-switchboard-token-abc123"
DEMO_KEY: str = "demo-opentable-key-AAAAAAAA"
ACME_KEY: str = "acme-opentable-key-BBBBBBBB"
# Per-restaurant RIDs (identifiers, not secrets) — paired with the API keys.
DEMO_RID: str = "rid-demo-1111"
ACME_RID: str = "rid-acme-2222"

# A fixed future datetime so tests are deterministic.
WHEN: str = "2026-07-01T19:00:00"


def auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    """Authorization header with a bearer token (valid by default)."""

    return {"Authorization": f"Bearer {token}"}


def availability_payload(tenant: str = "demo", party_size: int = 2) -> dict[str, object]:
    """A valid availability request body."""

    return {"tenant": tenant, "party_size": party_size, "datetime": WHEN}


def booking_payload(
    tenant: str = "demo",
    party_size: int = 2,
    name: str = "Ada Lovelace",
    idempotency_key: str = "idem-default-key",
) -> dict[str, object]:
    """A valid booking request body (idempotency_key is REQUIRED — review #5)."""

    return {
        "tenant": tenant,
        "name": name,
        "party_size": party_size,
        "datetime": WHEN,
        "idempotency_key": idempotency_key,
    }


def modify_payload(
    tenant: str = "demo",
    confirmation_id: str = "MOCK-DEMO-ABC123",
    idempotency_key: str = "idem-default-key",
) -> dict[str, object]:
    """A valid modify request body (idempotency_key REQUIRED)."""

    return {
        "tenant": tenant,
        "confirmation_id": confirmation_id,
        "idempotency_key": idempotency_key,
    }


def cancel_payload(
    tenant: str = "demo",
    confirmation_id: str = "MOCK-DEMO-ABC123",
    idempotency_key: str = "idem-default-key",
) -> dict[str, object]:
    """A valid cancel request body (idempotency_key REQUIRED)."""

    return {
        "tenant": tenant,
        "confirmation_id": confirmation_id,
        "idempotency_key": idempotency_key,
    }
