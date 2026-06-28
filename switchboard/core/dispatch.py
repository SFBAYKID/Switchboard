"""Latency-budget dispatch — bound the upstream wait, fail fast and cleanly.

Real-time endpoints (where a human may be waiting on the calling agent) carry a HARD
PER-ENDPOINT budget, and the caller may supply an even tighter deadline (review #4).
The mechanism (Rule 5 / architecture.md "Latency" / review #3-#4):

  - The effective timeout = min(per-endpoint budget, caller `X-Deadline-Ms`) minus a
    small safety margin, so Switchboard can always answer WITHIN the budget — with
    the upstream result OR a clean `timeout` outcome. It NEVER hangs the caller.
  - On timeout -> `TimeoutOutcome` (504, state="timeout", retryable). On any other
    upstream fault that isn't already a normalized outcome (connection error,
    malformed response, the not-yet-built real backend) -> `UnknownOutcome` (502,
    state="unknown"). A normalized `AppError` the backend raised itself (auth_error,
    rate_limited, requires_human, unavailable) passes through UNCHANGED.

Honest latency note: the localhost caller->gateway hop is sub-millisecond and is NOT
where time goes. The real cost is the upstream round trip — which is exactly what
this timeout bounds. `latency_ms` in the envelope is measured (see `api.timing`),
not guessed.

The raw upstream exception is deliberately NOT forwarded to the caller — it may carry
secrets, credentials, or PII (Rule 7 / review #2). We log only its type, never its
payload, and return a stable safe message.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import TypeVar

from switchboard.core.errors import (
    AppError,
    RequiresHumanOutcome,
    TimeoutOutcome,
    UnknownOutcome,
)

logger = logging.getLogger("switchboard.dispatch")

R = TypeVar("R")


def compute_effective_timeout_ms(
    *,
    budget_ms: int,
    caller_deadline_ms: int | None,
    margin_ms: int,
) -> int:
    """Resolve the effective upstream timeout from the budget and caller deadline.

    Takes the tighter of the per-endpoint budget and the caller-supplied deadline
    (review #4: deadline propagation), then leaves a safety margin so the envelope is
    built and returned WITHIN the budget. Always at least 1ms.

    Args:
        budget_ms: the per-endpoint budget (e.g. availability ~1500ms).
        caller_deadline_ms: the caller's hard deadline in ms (X-Deadline-Ms), if any.
        margin_ms: ms reserved to build/return the envelope within budget.
    """

    budget = budget_ms
    if caller_deadline_ms is not None and caller_deadline_ms > 0:
        budget = min(budget, caller_deadline_ms)
    return max(1, budget - margin_ms)


async def call_with_budget(
    awaitable: Awaitable[R],
    *,
    timeout_ms: int,
    source: str,
    mock: bool,
    is_write: bool = False,
) -> R:
    """Await `awaitable` under a hard timeout, mapping faults to normalized outcomes.

    Args:
        awaitable: the in-flight backend coroutine (e.g. `backend.availability(...)`).
        timeout_ms: effective upstream timeout in ms (from compute_effective_timeout_ms).
        source: integration source label for any error envelope (e.g. "reservations").
        mock: whether the active backend is a mock (for the envelope's `mock` flag).
        is_write: whether this is a consequential write. A write that times out is
            AMBIGUOUS — the upstream may already have committed before cancellation —
            so it must NOT be returned as a blindly-retryable `timeout` (that invites
            a double-book). It is surfaced as `requires_human` instead (review #5).

    Returns:
        The backend's result on success.

    Raises:
        TimeoutOutcome: a READ exceeded the timeout (504, state="timeout", retryable).
        RequiresHumanOutcome: a WRITE exceeded the timeout (409, ambiguous, not
            blindly retryable).
        UnknownOutcome: any other unclassified upstream fault (502, state="unknown").
        AppError: re-raised unchanged if the backend already raised a normalized one.
    """

    try:
        # asyncio.wait_for cancels the underlying coroutine on timeout, so a slow
        # upstream task does not leak past the budget. (The real backend additionally
        # bounds its OWN client via deadline_ms so a write is aborted cleanly, not
        # cancelled mid-flight.)
        return await asyncio.wait_for(awaitable, timeout=timeout_ms / 1000.0)
    except asyncio.TimeoutError as exc:
        if is_write:
            # Ambiguous write: do not present a retryable timeout. Require human
            # reconciliation before any retry (the write may have committed).
            raise RequiresHumanOutcome(
                "The write exceeded its deadline and may or may not have completed; "
                "reconcile before retrying.",
                source=source,
                mock=mock,
            ) from exc
        # A read was too slow. Answer promptly with a clean, retryable timeout.
        raise TimeoutOutcome(source=source, mock=mock) from exc
    except AppError:
        # The backend raised a normalized outcome it already mapped to the contract
        # (auth_error / rate_limited / requires_human / unavailable). Pass through.
        raise
    except Exception as exc:  # noqa: BLE001 — intentional: convert ALL else to a safe outcome
        # Never leak the raw upstream error to the caller. Log only the type.
        logger.warning("upstream fault in source=%s: %s", source, type(exc).__name__)
        raise UnknownOutcome(source=source, mock=mock) from exc
