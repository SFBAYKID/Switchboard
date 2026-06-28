"""System endpoints — liveness + version info, no auth, no secrets."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import ACME_KEY, DEMO_KEY, TEST_TOKEN


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_health_alias(client: TestClient) -> None:
    # The documented Postman/CI healthcheck polls /health.
    assert client.get("/health").status_code == 200


def test_version_info_lists_only_built_integrations(client: TestClient) -> None:
    body = client.get("/v1").json()
    assert body["name"] == "Switchboard"
    assert body["api_version"] == "v1"
    # Only BUILT integrations are advertised; future seams are absent.
    assert body["integrations"] == ["reservations"]
    assert "payments" not in body["integrations"]
    assert "website" not in body["integrations"]


def test_system_endpoints_leak_no_secrets(client: TestClient) -> None:
    for path in ("/healthz", "/v1"):
        text = client.get(path).text
        assert TEST_TOKEN not in text
        assert DEMO_KEY not in text
        assert ACME_KEY not in text


def test_correlation_header_present(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert "X-Request-ID" in resp.headers
