"""Per-tenant credential resolution (architecture.md "Per-tenant credentials").

Switchboard is multi-tenant at the credential layer: tenant A's OpenTable account
is NOT tenant B's. A caller sends only a `tenant` IDENTIFIER — never a credential —
and Switchboard resolves that tenant's upstream secret here, from its OWN secret
store (the environment).

Security properties this module guarantees (and that tests assert):
  - **Structural per-tenant isolation.** The env var name is derived from the
    EXACT requested tenant: `SWITCHBOARD_<NAMESPACE>__<TENANT>__API_KEY`. There is
    no code path that returns tenant B's key for a tenant A request — the lookup
    key is a pure function of (namespace, requested tenant).
  - **Fail closed.** An unknown/unconfigured tenant raises `TenantNotFoundError`
    (404). Switchboard NEVER falls back to a default tenant's credentials.
  - **No disclosure.** Errors never reveal which tenants exist, and the resolved
    secret is NEVER logged or placed in any envelope/error (it is returned only to
    the backend that makes the upstream call).

Tenant names are case-insensitive: they are uppercased to form the env var name, so
`demo`, `Demo`, and `DEMO` resolve to the same `SWITCHBOARD_OPENTABLE__DEMO__API_KEY`.
The inbound request layer additionally restricts tenant to `[A-Za-z0-9_-]+`; this
module re-validates defensively before building an env var name.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from switchboard.core.errors import BadRequestError, TenantNotFoundError

# A tenant identifier must be a safe slug. Re-validated here (defense in depth) even
# though the request models also constrain it, because this value is interpolated
# into an environment variable name.
_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class ResolvedCredential:
    """A resolved upstream credential for one (integration, tenant).

    `api_key` is SECRET: never log it, never echo it into a response/error envelope.
    `repr=False` keeps it out of accidental `repr()`/log lines (e.g. if the dataclass
    is logged). It is passed only to the backend that performs the upstream call.
    """

    integration: str  # credential namespace, e.g. "OPENTABLE"
    tenant: str  # the resolved tenant slug (uppercased), an identifier, not a secret
    api_key: str = field(repr=False)  # SECRET — kept out of repr/logs


def _env_var_name(namespace: str, tenant: str) -> str:
    """Build the namespaced env var name for a (namespace, tenant) credential."""

    return f"SWITCHBOARD_{namespace.upper()}__{tenant.upper()}__API_KEY"


def resolve_credential(
    namespace: str,
    tenant: str,
    *,
    source: str,
    mock: bool,
) -> ResolvedCredential:
    """Resolve the upstream credential for (namespace, tenant), or fail closed.

    `source`/`mock` are envelope-tagging metadata stamped onto any raised error so
    the failure envelope correctly attributes itself to the calling integration.

    Raises:
        BadRequestError: the tenant identifier is malformed.
        TenantNotFoundError: no credential is configured for this tenant (fail closed).
    """

    if not _TENANT_RE.match(tenant):
        # Don't echo the raw value back (avoid reflecting arbitrary input).
        raise BadRequestError(
            "The 'tenant' identifier is malformed.", source=source, mock=mock
        )

    var_name = _env_var_name(namespace, tenant)
    value = os.environ.get(var_name)
    if not value:
        # Fail CLOSED. Generic message: never disclose which tenants are configured.
        raise TenantNotFoundError(source=source, mock=mock)

    return ResolvedCredential(
        integration=namespace.upper(),
        tenant=tenant.upper(),
        api_key=value,
    )


def configured_tenants(namespace: str) -> set[str]:
    """Return the set of tenant slugs configured for `namespace` (uppercased).

    Used at startup to verify at least one tenant is configured (fail loud), and
    by tests. Reads `os.environ` directly so it sees both real env vars and any
    `.env` values that `get_settings()` loaded into the process environment.
    """

    prefix = f"SWITCHBOARD_{namespace.upper()}__"
    suffix = "__API_KEY"
    tenants: set[str] = set()
    for key, value in os.environ.items():
        if key.startswith(prefix) and key.endswith(suffix) and value:
            tenants.add(key[len(prefix) : -len(suffix)])
    return tenants
