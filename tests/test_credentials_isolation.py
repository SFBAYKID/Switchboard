"""Per-restaurant credential isolation + secret non-leak (a do-not-ship surface)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from switchboard.core.credentials import configured_tenants, resolve_credential
from switchboard.core.errors import TenantNotFoundError
from tests.helpers import (
    ACME_KEY,
    DEMO_KEY,
    DEMO_RID,
    auth_headers,
    availability_payload,
    booking_payload,
    write_headers,
)

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"


def test_resolver_returns_distinct_per_restaurant() -> None:
    demo = resolve_credential("OPENTABLE", "demo", source="reservations", mock=True)
    acme = resolve_credential("OPENTABLE", "acme", source="reservations", mock=True)
    assert demo.api_key == DEMO_KEY
    assert acme.api_key == ACME_KEY
    assert demo.api_key != acme.api_key  # no cross-bleed


def test_resolver_returns_rid_paired_with_key() -> None:
    # The RID is resolved alongside the API key so go-live is "set RID + key".
    demo = resolve_credential("OPENTABLE", "demo", source="reservations", mock=True)
    assert demo.rid == DEMO_RID


def test_unknown_restaurant_fails_closed() -> None:
    # Fail CLOSED: never fall back to a default restaurant's credentials.
    with pytest.raises(TenantNotFoundError):
        resolve_credential("OPENTABLE", "ghosttenant", source="reservations", mock=True)


def test_resolution_is_case_insensitive() -> None:
    upper = resolve_credential("OPENTABLE", "DEMO", source="reservations", mock=True)
    assert upper.api_key == DEMO_KEY


def test_configured_restaurants_set() -> None:
    assert configured_tenants("OPENTABLE") == {"DEMO", "ACME"}


def test_unknown_restaurant_endpoint_returns_404(client: TestClient) -> None:
    resp = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(restaurant_id="ghosttenant")
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert body["state"] is None


def test_no_secret_ever_appears_in_a_response(client: TestClient) -> None:
    for restaurant in ("demo", "acme"):
        avail = client.post(AVAIL, headers=auth_headers(), json=availability_payload(restaurant_id=restaurant))
        booking = client.post(
            BOOK, headers=write_headers(f"leak-{restaurant}"), json=booking_payload(restaurant_id=restaurant)
        )
        for resp in (avail, booking):
            assert DEMO_KEY not in resp.text
            assert ACME_KEY not in resp.text
    # ...and the fail-closed error response, too.
    err = client.post(AVAIL, headers=auth_headers(), json=availability_payload(restaurant_id="ghosttenant"))
    assert DEMO_KEY not in err.text
    assert ACME_KEY not in err.text


def test_confirmations_are_restaurant_tagged_and_distinct(client: TestClient) -> None:
    # Same Idempotency-Key, different restaurants -> different confirmations (no cross-bleed).
    demo = client.post(
        BOOK, headers=write_headers("same"), json=booking_payload(restaurant_id="demo")
    ).json()
    acme = client.post(
        BOOK, headers=write_headers("same"), json=booking_payload(restaurant_id="acme")
    ).json()
    assert demo["data"]["confirmation_id"].startswith("MOCK-DEMO-")
    assert acme["data"]["confirmation_id"].startswith("MOCK-ACME-")
    assert demo["data"]["confirmation_id"] != acme["data"]["confirmation_id"]
