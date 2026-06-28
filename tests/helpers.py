"""Shared test constants + helpers.

TEST values only — Switchboard's real secrets live in its gitignored .env and are
never used here. The suite is fully hermetic (SWITCHBOARD_DISABLE_DOTENV=1).

Contract under test (Switchboard's OWN normalized reservations contract):
  - identifier: `restaurant_id`
  - split `date` (YYYY-MM-DD) + `time` (HH:MM)
  - booking carries a `customer` object + optional `notes`
  - writes require the `Idempotency-Key` HEADER (not a body field)
"""

from __future__ import annotations

# The uniform envelope's exact field set — asserted identical on success AND error.
ENVELOPE_FIELDS: frozenset[str] = frozenset(
    {"ok", "state", "data", "error", "source", "latency_ms", "mock", "request_id"}
)

# Test bearer token + two distinct restaurant credentials (for isolation tests). The
# two api-key VALUES are deliberately distinct so a leak/cross-bleed is detectable.
TEST_TOKEN: str = "test-switchboard-token-abc123"
DEMO_KEY: str = "demo-opentable-key-AAAAAAAA"
ACME_KEY: str = "acme-opentable-key-BBBBBBBB"
# Per-restaurant RIDs (identifiers, not secrets) — paired with the API keys.
DEMO_RID: str = "rid-demo-1111"
ACME_RID: str = "rid-acme-2222"

# Seeded slots for DEMO/ACME on this date (data/mock_reservations.json).
DATE: str = "2026-07-01"
TIME: str = "19:00"  # capacity 10
SCARCE_TIME: str = "19:30"  # capacity 1 — drives the availability!=booked race


def auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    """Authorization header with a bearer token (valid by default)."""

    return {"Authorization": f"Bearer {token}"}


def write_headers(
    idempotency_key: str = "idem-default-key", token: str = TEST_TOKEN
) -> dict[str, str]:
    """Headers for a WRITE: bearer auth + the required Idempotency-Key header."""

    return {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key}


def availability_payload(
    restaurant_id: str = "demo",
    party_size: int = 2,
    date: str = DATE,
    time: str = TIME,
) -> dict[str, object]:
    """A valid availability request body."""

    return {"restaurant_id": restaurant_id, "date": date, "time": time, "party_size": party_size}


def booking_payload(
    restaurant_id: str = "demo",
    party_size: int = 2,
    date: str = DATE,
    time: str = TIME,
    name: str = "Ada Lovelace",
    phone: str = "+14155551212",
    email: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    """A valid booking request body (idempotency goes in the Idempotency-Key header)."""

    customer: dict[str, object] = {"name": name, "phone": phone}
    if email is not None:
        customer["email"] = email
    body: dict[str, object] = {
        "restaurant_id": restaurant_id,
        "date": date,
        "time": time,
        "party_size": party_size,
        "customer": customer,
    }
    if notes is not None:
        body["notes"] = notes
    return body


def modify_payload(
    restaurant_id: str = "demo",
    confirmation_id: str = "MOCK-DEMO-ABC123",
    date: str | None = None,
    time: str | None = None,
    party_size: int | None = None,
) -> dict[str, object]:
    """A valid modify request body (idempotency goes in the header)."""

    body: dict[str, object] = {"restaurant_id": restaurant_id, "confirmation_id": confirmation_id}
    if date is not None:
        body["date"] = date
    if time is not None:
        body["time"] = time
    if party_size is not None:
        body["party_size"] = party_size
    return body


def cancel_payload(
    restaurant_id: str = "demo",
    confirmation_id: str = "MOCK-DEMO-ABC123",
) -> dict[str, object]:
    """A valid cancel request body (idempotency goes in the header)."""

    return {"restaurant_id": restaurant_id, "confirmation_id": confirmation_id}
