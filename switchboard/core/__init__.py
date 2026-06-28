"""Switchboard core — shared, vendor-agnostic plumbing.

Everything in here is integration-agnostic: the uniform response envelope, the
structured error types + HTTP-status mapping, fail-loud config, the per-tenant
credential resolver, and the latency-budget dispatch helper. Integration modules
(reservations, future payments/website) build ON these; nothing here knows any
specific vendor's API.
"""

from __future__ import annotations
