"""Reservations request/result models (the typed data shapes).

These model the `data`-side shapes for the reservations endpoints. They are the
contract the MOCK backend and the future real OpenTable backend BOTH satisfy — so
swapping mock -> real changes nothing for the caller (Rule 12: model the shapes as
explicit, precise types so mock and real are provably identical).

Normalized states (review #2/#3): a real-time endpoint's outcome is exactly one
normalized `state`. The SUCCESS states live in these result models:
  - availability: `available` | `unavailable`
  - book:         `confirmed`
  - modify:       `modified`
  - cancel:       `cancelled`
The non-definitive states (`unknown`, `timeout`, `auth_error`, `rate_limited`,
`requires_human`, and booking's `unavailable` race) are NOT successes — they are
raised as `AppError` outcomes (see `core.errors`) and surfaced as `ok=false` with the
normalized `state`. So a result model here only ever represents a definitive success,
and a confirmation id only ever exists on an actual confirmation (no false success).

Idempotency (review #5): every WRITE (book/modify/cancel) accepts an
`idempotency_key` so a retried write cannot double-act.

The deadline (review #4) is NOT a body field — it is the `X-Deadline-Ms` request
header (a cross-cutting concern), parsed in the API layer.

NOTE on field name `datetime`: the public contract uses `datetime`, so the module is
imported as `dt` to avoid shadowing while keeping the field name.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# The full normalized-state vocabulary for reservation real-time endpoints (review
# #2). Documented here for reference; success states are used in the result models,
# failure/ambiguous states are carried by the error classes in core.errors.
ReservationState = Literal[
    "available",
    "unavailable",
    "confirmed",
    "modified",
    "cancelled",
    "unknown",
    "timeout",
    "auth_error",
    "rate_limited",
    "requires_human",
]

# A tenant identifier: an IDENTIFIER, never a credential. Constrained to a safe slug
# because it is later used (uppercased) to resolve a per-tenant credential env var.
Tenant = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]

# Party size bounds: at least 1; an upper bound keeps absurd inputs out and lets the
# mock model a realistic "too large to book online" case.
PartySize = Annotated[int, Field(ge=1, le=100)]

# An idempotency key for writes: optional but recommended; bounded length.
IdempotencyKey = Annotated[str | None, Field(default=None, max_length=200)]


# ── Requests ───────────────────────────────────────────────────────────────────


class AvailabilityRequest(BaseModel):
    """`POST /v1/reservations/availability` body (real-time, deadline-budgeted)."""

    tenant: Tenant
    party_size: PartySize
    datetime: dt.datetime  # requested reservation time (ISO 8601)


class BookingRequest(BaseModel):
    """`POST /v1/reservations/book` body (a consequential write — Rule 9 / review #5).

    `idempotency_key` makes the write retry-safe: a retried `book` with the same key
    must NOT create a second booking. The mock derives a deterministic
    confirmation_id from the key to demonstrate this at the contract level; the real
    backend forwards the key to OpenTable's idempotency mechanism (verified against
    OpenTable docs before that backend is written — Rule 2).
    """

    tenant: Tenant
    name: str = Field(min_length=1, max_length=200)  # guest name on the booking
    party_size: PartySize
    datetime: dt.datetime
    idempotency_key: IdempotencyKey = None


class ModifyRequest(BaseModel):
    """`POST /v1/reservations/modify` body (a consequential write — Rule 9 / review #5)."""

    tenant: Tenant
    confirmation_id: str = Field(min_length=1, max_length=200)
    party_size: PartySize | None = None  # new size, if changing
    datetime: dt.datetime | None = None  # new time, if changing
    idempotency_key: IdempotencyKey = None


class CancelRequest(BaseModel):
    """`POST /v1/reservations/cancel` body (a consequential write — Rule 9 / review #5)."""

    tenant: Tenant
    confirmation_id: str = Field(min_length=1, max_length=200)
    idempotency_key: IdempotencyKey = None


# ── Results (the `data` payloads — definitive successes only) ─────────────────────


class AvailabilitySlot(BaseModel):
    """One bookable slot returned by availability."""

    time: dt.datetime
    party_size: int


class AvailabilityResult(BaseModel):
    """`data` for availability: the normalized success state + candidate slots.

    `state` is `available` (slots present) or `unavailable` (none). Non-definitive
    outcomes (timeout/auth_error/…) never reach here — they are raised as errors.
    """

    state: Literal["available", "unavailable"]
    slots: list[AvailabilitySlot]


class BookingResult(BaseModel):
    """`data` for book: an actual confirmation only.

    `state` is always `confirmed` and `confirmation_id` is always present. Any
    non-confirmed booking outcome (slot gone, ambiguous, timeout, …) is raised as an
    error so this success shape can never carry a false/empty confirmation.
    """

    state: Literal["confirmed"]
    confirmation_id: str


class ModifyResult(BaseModel):
    """`data` for modify: the confirmation id + `modified` state."""

    state: Literal["modified"]
    confirmation_id: str


class CancelResult(BaseModel):
    """`data` for cancel: the confirmation id + `cancelled` state."""

    state: Literal["cancelled"]
    confirmation_id: str
