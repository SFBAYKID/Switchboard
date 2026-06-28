"""Switchboard integrations — one self-contained module per integration.

The load-bearing structural rule (architecture.md): **adding a new integration
never touches an existing one.** Each integration lives in its own package, owns
its own request/response models, its own backend interface, and its own mock + real
backends. The API layer dispatches through the uniform interface and the uniform
envelope; it knows no vendor specifics.

BUILT:
  - `reservations`  — OpenTable, mock-first. The first and only module built now.

CLEARLY-MARKED FUTURE SEAMS (plan — NOT built; do not implement ahead of need,
per CLAUDE.md "Scope — build seams, not the future"):
  - `payments`  — Stripe. Same uniform interface + mock-first. Added as a NEW
                  package + route registration; never edits `reservations`.
  - `website`   — scraping/crawl. ASYNC (returns a job_id; off the real-time budget).

When a future module is built it follows the reservations module's shape exactly:
models.py, interface.py (typed Protocol), backend_mock.py (default), and a
clearly-marked real backend whose vendor specifics are verified against official
docs BEFORE it is written (CLAUDE.md Rule 2).
"""

from __future__ import annotations
