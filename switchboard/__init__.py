"""Switchboard — the Integration Gateway.

A standalone, lightweight internal HTTP API service whose single job is to connect
to third-party APIs (OpenTable, Stripe, website scraping, and whatever comes next)
and return their data to internal callers over one clean, versioned, token-gated
internal contract — always wrapped in the same uniform response envelope.

This package is organized as:
  - `switchboard.core`         shared, vendor-agnostic plumbing (envelope, errors,
                               config, credential resolver, latency/dispatch).
  - `switchboard.integrations` one self-contained module per integration behind a
                               uniform interface (reservations now; payments/website
                               are clearly-marked future seams).
  - `switchboard.api`          the FastAPI app: token gate, routing, envelope
                               wrapping, latency timing, exception handlers.

Switchboard is a brand-new, standalone project (isolation rule): it assumes NO
pre-existing infrastructure and holds only its OWN secrets in its OWN .env.
"""

from __future__ import annotations

__version__ = "0.1.0"
