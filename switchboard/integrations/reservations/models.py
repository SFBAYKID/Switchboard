"""Reservations request/result models (the typed data shapes) — domain-shaped.

These model the `data`-side shapes for the reservations endpoints, shaped for the
caller's domain (a voice agent booking restaurant reservations): a `restaurant_id`
identifier, split `date` + `time`, and a `customer` object with `notes` on booking.
They are the contract the MOCK backend and the future real OpenTable backend BOTH
satisfy — so swapping mock -> real changes nothing for the caller (Rule 12).

VERIFICATION STATUS (Rule 1/2/6 — read before trusting these shapes): this is
**Switchboard's OWN normalized contract**, NOT a description of OpenTable's API.
OpenTable's API is partner-gated and not publicly documented, so the OpenTable backing
of the following is **UNVERIFIED and subject to change at integration**: the `book`,
`modify`, and `cancel` operations (server-side write support for our partner tier is
unconfirmed — affiliate tiers may be reservation-link only), and the `customer.email`
and `notes` fields (whether OpenTable accepts/returns them is unconfirmed). The
identifier/date/time/slots/envelope shapes ARE the gateway's own normalization and are
stable for the caller. See architecture.md "OpenTable integration — verification
status" for what must be confirmed once partner approval lands.

Identifier mapping: `restaurant_id` is the caller-facing identifier. Internally it is
the gateway's per-credential "tenant" key — Switchboard resolves it to that
restaurant's OpenTable RID + API key (`SWITCHBOARD_OPENTABLE__<RESTAURANT_ID>__*`).
The caller never sends the RID or any upstream key.

Idempotency (review #5) is supplied via the REQUIRED `Idempotency-Key` HEADER on
writes (not a body field), so the JSON body stays clean and matches a standard
idempotent-write convention. The deadline (review #4) is the `X-Deadline-Ms` header.

Time handling: `date` is `YYYY-MM-DD`; `time` is `HH:MM` 24-hour in the restaurant's
LOCAL time. `combined_datetime()` joins them for internal slot matching.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# The caller-facing restaurant identifier (a safe slug). Maps internally to the
# per-credential tenant key used to resolve OpenTable RID + API key.
RestaurantId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Switchboard restaurant identifier (NOT the OpenTable RID/key).",
    ),
]

# `time` as HH:MM, 24-hour, restaurant-local. Kept as a validated string (rather than
# a time type) so it echoes back exactly as sent.
TimeHHMM = Annotated[
    str,
    Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$", description="HH:MM (24-hour, restaurant local)."),
]

# Party size: 1-100; >12 is treated as not bookable online (mirrors real life).
PartySize = Annotated[int, Field(ge=1, le=100)]


def combined_datetime(date: dt.date, time_hhmm: str) -> dt.datetime:
    """Combine a date + an HH:MM string into a naive local datetime (slot key)."""

    hour, minute = (int(part) for part in time_hhmm.split(":"))
    return dt.datetime.combine(date, dt.time(hour=hour, minute=minute))


# ── Requests ───────────────────────────────────────────────────────────────────


class AvailabilityRequest(BaseModel):
    """`POST /v1/reservations/availability` body (real-time, deadline-budgeted)."""

    restaurant_id: RestaurantId
    date: dt.date  # YYYY-MM-DD
    time: TimeHHMM  # HH:MM (restaurant local)
    party_size: PartySize


class Customer(BaseModel):
    """The guest the reservation is for. `name` + `phone` are required for a booking."""

    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=3, max_length=40)  # caller's number (E.164 preferred)
    email: str | None = Field(default=None, max_length=320)


class BookingRequest(BaseModel):
    """`POST /v1/reservations/book` body (a consequential write — Rule 9 / review #5).

    Retry-safety is provided by the REQUIRED `Idempotency-Key` request header, NOT a
    body field: a retried book with the same key must not create a second booking.
    """

    restaurant_id: RestaurantId
    date: dt.date
    time: TimeHHMM
    party_size: PartySize
    customer: Customer
    notes: str | None = Field(default=None, max_length=1000)


class ModifyRequest(BaseModel):
    """`POST /v1/reservations/modify` body (a consequential write).

    Provide the fields you want to change (date/time/party_size). Idempotency-Key
    header required.
    """

    restaurant_id: RestaurantId
    confirmation_id: str = Field(min_length=1, max_length=200)
    date: dt.date | None = None
    time: TimeHHMM | None = None
    party_size: PartySize | None = None


class CancelRequest(BaseModel):
    """`POST /v1/reservations/cancel` body (a consequential write). Idempotency-Key required."""

    restaurant_id: RestaurantId
    confirmation_id: str = Field(min_length=1, max_length=200)


# ── Results (the `data` payloads — definitive successes only) ─────────────────────


class AvailabilitySlot(BaseModel):
    """One bookable slot (date + HH:MM time + the party size it was checked for)."""

    date: dt.date
    time: TimeHHMM
    party_size: int


class AvailabilityResult(BaseModel):
    """`data` for availability.

    `state` is `available` when the REQUESTED date/time is bookable, else
    `unavailable`. `slots` lists the open slots that day (the requested one if open,
    plus alternatives) so the caller can offer options either way.
    """

    state: Literal["available", "unavailable"]
    slots: list[AvailabilitySlot]


class BookingResult(BaseModel):
    """`data` for book: an actual confirmation only (`state` always `confirmed`)."""

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
