"""Switchboard API routes — capability-shaped endpoints, one router per concern.

Per the architecture review (#1), routes are CONCRETE and capability-shaped
(`/v1/reservations/availability`, `/v1/reservations/book`, …) — NOT a generic
`/integrations/{name}/invoke` executor. Each future integration adds its own
capability-shaped router here; adding one never touches an existing one.
"""

from __future__ import annotations
