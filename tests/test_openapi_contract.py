"""The published OpenAPI contract must tell the truth (charter Principle 1).

Regression guards for QA findings F1 (the spec documented a 422 the app never emits
and omitted the real error responses) and F2 (no bearer security scheme declared).
"""

from __future__ import annotations

from switchboard.api.main import app

AVAIL = "/v1/reservations/availability"
BOOK = "/v1/reservations/book"
RESERVATION_PATHS = (
    AVAIL,
    BOOK,
    "/v1/reservations/modify",
    "/v1/reservations/cancel",
)


def test_no_spurious_422_on_any_operation() -> None:
    # Validation maps to 400 + the uniform envelope; the app never returns 422.
    spec = app.openapi()
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if not isinstance(op, dict) or "responses" not in op:
                continue
            assert "422" not in op["responses"], f"422 leaked into {method.upper()} {path}"


def test_real_error_responses_documented() -> None:
    spec = app.openapi()
    avail = set(spec["paths"][AVAIL]["post"]["responses"])
    assert {"200", "400", "401", "404", "429", "502", "504"} <= avail
    # Writes additionally document the 409 race/ambiguous outcomes.
    book = set(spec["paths"][BOOK]["post"]["responses"])
    assert "409" in book


def test_bearer_security_scheme_declared_and_required() -> None:
    spec = app.openapi()
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert "BearerAuth" in schemes
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    # Required on every gated reservations operation...
    for path in RESERVATION_PATHS:
        op = spec["paths"][path]["post"]
        assert op.get("security") == [{"BearerAuth": []}], f"missing security on {path}"


def test_system_endpoints_are_open() -> None:
    spec = app.openapi()
    for path in ("/healthz", "/health", "/v1"):
        assert "security" not in spec["paths"][path]["get"]
