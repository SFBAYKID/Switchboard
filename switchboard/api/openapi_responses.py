"""Documented error responses for the OpenAPI spec (so the contract tells the truth).

The charter's #1 principle is that the OpenAPI spec is the source of truth and must
not lie about the running service. By default FastAPI documents only the 200 success
and an auto `422` — but Switchboard maps validation to `400` + the uniform envelope
and never emits a 422 (the 422 is stripped in `api.main`'s custom `openapi()`). These
dicts declare the REAL error responses each route can return, all using the uniform
`ErrorEnvelope` shape, so a caller generating a client sees the full failure contract
(and the normalized `state` / `error.code` vocabulary it must branch on).
"""

from __future__ import annotations

from typing import Any

from switchboard.core.envelope import ErrorEnvelope

# Errors any real-time reservations endpoint can return.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope, "description": "Invalid request — error.code=bad_request (state=null)."},
    401: {"model": ErrorEnvelope, "description": "Missing/invalid bearer token — error.code=unauthorized (state=null)."},
    404: {"model": ErrorEnvelope, "description": "Unknown tenant, fail closed — error.code=not_found (state=null)."},
    429: {"model": ErrorEnvelope, "description": "Upstream rate-limited — state=rate_limited."},
    502: {"model": ErrorEnvelope, "description": "Upstream auth failure or unusable response — state=auth_error|unknown."},
    504: {"model": ErrorEnvelope, "description": "Upstream exceeded the deadline — state=timeout."},
}

# Writes (book/modify/cancel) can additionally return 409 for the ambiguous /
# slot-gone outcomes (review #5): never a false confirmation.
WRITE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **COMMON_ERROR_RESPONSES,
    409: {"model": ErrorEnvelope, "description": "Ambiguous or slot-gone outcome — state=requires_human|unavailable."},
}
