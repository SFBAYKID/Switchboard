"""The internal token gate (caller -> gateway hop).

Every request to a `/v1` capability endpoint must carry a valid bearer token
(architecture.md "Transport: token-gated localhost"; charter Principle 5). This is
Switchboard's OWN secret, held in its OWN environment — not borrowed from anything.

A missing or invalid token raises `UnauthorizedError`, which the exception handler
renders as a well-formed `401` error envelope (NOT FastAPI's default `{"detail": …}`
shape, and NOT a raw framework error — QA: the unauthorized response is still a
well-formed envelope).

This is the INTERNAL auth boundary (the caller's gateway token). It is distinct from
an upstream `auth_error` (a tenant's vendor credential being rejected) — see
`core.errors`.

Security: the token comparison uses `secrets.compare_digest` (constant-time) so a
timing side-channel can't be used to guess the token. The token is never logged.
"""

from __future__ import annotations

import secrets

from fastapi import Depends
from starlette.requests import Request

from switchboard.core.config import Settings, get_settings
from switchboard.core.errors import UnauthorizedError

_BEARER_PREFIX = "Bearer "


def _token_is_valid(presented: str, settings: Settings) -> bool:
    """Constant-time compare of the presented token against the configured token."""

    return secrets.compare_digest(presented, settings.api_token)


def require_bearer_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency: enforce a valid `Authorization: Bearer <token>` header.

    Raises:
        UnauthorizedError: the header is missing, malformed, or the token is invalid.
            (Generic message — never reveals whether/which token would be valid.)
    """

    header = request.headers.get("Authorization")
    if not header or not header.startswith(_BEARER_PREFIX):
        raise UnauthorizedError()

    presented = header[len(_BEARER_PREFIX) :].strip()
    if not presented or not _token_is_valid(presented, settings):
        raise UnauthorizedError()
