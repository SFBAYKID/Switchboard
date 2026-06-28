"""Per-tenant credential isolation + secret non-leak (a do-not-ship surface)."""

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
)

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"


def test_resolver_returns_distinct_per_tenant() -> None:
    demo = resolve_credential("OPENTABLE", "demo", source="reservations", mock=True)
    acme = resolve_credential("OPENTABLE", "acme", source="reservations", mock=True)
    assert demo.api_key == DEMO_KEY
    assert acme.api_key == ACME_KEY
    assert demo.api_key != acme.api_key  # no cross-bleed


def test_resolver_returns_rid_paired_with_key() -> None:
    # The RID is resolved alongside the API key so go-live is "set RID + key".
    demo = resolve_credential("OPENTABLE", "demo", source="reservations", mock=True)
    assert demo.rid == DEMO_RID


def test_unknown_tenant_fails_closed() -> None:
    # Fail CLOSED: never fall back to a default tenant's credentials.
    with pytest.raises(TenantNotFoundError):
        resolve_credential("OPENTABLE", "ghosttenant", source="reservations", mock=True)


def test_tenant_resolution_is_case_insensitive() -> None:
    upper = resolve_credential("OPENTABLE", "DEMO", source="reservations", mock=True)
    assert upper.api_key == DEMO_KEY


def test_configured_tenants_set() -> None:
    assert configured_tenants("OPENTABLE") == {"DEMO", "ACME"}


def test_unknown_tenant_endpoint_returns_404(client: TestClient) -> None:
    resp = client.post(
        AVAIL, headers=auth_headers(), json=availability_payload(tenant="ghosttenant")
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert body["state"] is None


def test_no_secret_ever_appears_in_a_response(client: TestClient) -> None:
    # Success responses for both tenants...
    for tenant in ("demo", "acme"):
        avail = client.post(AVAIL, headers=auth_headers(), json=availability_payload(tenant=tenant))
        booking = client.post(BOOK, headers=auth_headers(), json=booking_payload(tenant=tenant))
        for resp in (avail, booking):
            assert DEMO_KEY not in resp.text
            assert ACME_KEY not in resp.text
    # ...and the fail-closed error response, too.
    err = client.post(AVAIL, headers=auth_headers(), json=availability_payload(tenant="ghosttenant"))
    assert DEMO_KEY not in err.text
    assert ACME_KEY not in err.text


def test_confirmations_are_tenant_tagged_and_distinct(client: TestClient) -> None:
    demo = client.post(
        BOOK, headers=auth_headers(), json=booking_payload(tenant="demo", idempotency_key="same")
    ).json()
    acme = client.post(
        BOOK, headers=auth_headers(), json=booking_payload(tenant="acme", idempotency_key="same")
    ).json()
    # Same idempotency key, different tenants -> different confirmations (no cross-bleed).
    assert demo["data"]["confirmation_id"].startswith("MOCK-DEMO-")
    assert acme["data"]["confirmation_id"].startswith("MOCK-ACME-")
    assert demo["data"]["confirmation_id"] != acme["data"]["confirmation_id"]
