# Prompt for the nico-project agent — integrating with Switchboard (Reservations API)

> Paste everything below the line to the Claude working on the **nico** project. Two
> values are environment-specific and the operator will give them to you: the **base
> URL** and the **bearer token** (marked `<...>`).

---

You are integrating **nico** — a **live voice phone agent** — with **Switchboard**, an
internal HTTP API gateway that owns third-party integrations. Your integration is
**Reservations**.

**The call flow you are implementing:** a customer calls in → normal greeting → asks
for a reservation (a restaurant, a date, a time, a party size). nico says *"One second,
let me check availability for you,"* and **calls Switchboard's availability endpoint**.
If available, nico says *"Yes, that time is available."* The customer confirms → nico
says *"Okay, great,"* and **calls Switchboard's booking endpoint** to reserve it. nico
collects the details conversationally, but when it calls Switchboard it must send a
**structured JSON object with all required fields**.

## CRITICAL — read this first (honesty about the data)
- Switchboard is in **mock mode** today. It returns **fake but contract-shaped**
  reservation data through the real code path, so you can build and fully test the
  nico↔Switchboard loop **now**, before OpenTable access exists. Every response has
  `"mock": true`. When real OpenTable access lands, `mock` flips to `false` and **your
  code does not change**.
- **This contract is Switchboard's OWN normalized shape — NOT a copy of OpenTable's
  API.** OpenTable's API is partner-gated and not publicly documented, so the OpenTable
  backing of `book`/`modify`/`cancel` and the `customer.email`/`notes` fields is
  **unverified and may change at integration**. Build to *Switchboard's* contract below;
  do not assume these are OpenTable's field names. If you need a field/operation that
  isn't here, tell us — don't invent one.

## Ground rules
- **You are just an HTTP client.** You never hold OpenTable credentials or call
  OpenTable directly. You send Switchboard a bearer token + a `restaurant_id`;
  Switchboard resolves that restaurant's upstream credentials itself.
- **You own the fallback.** Switchboard returns a *normalized state* fast; deciding what
  nico says/does (retry, offer another time, take a message, escalate) is your job.
- **Never assume a booking happened.** A reservation is made **only** when you get
  `"state": "confirmed"` with a `confirmation_id`. Anything else is not a booking.

## Connection
- **Base URL (dev):** `<BASE_URL>` (e.g. `http://127.0.0.1:8080` — localhost, internal only)
- **Auth:** every `/v1/...` request sends `Authorization: Bearer <SWITCHBOARD_TOKEN>`.
- **restaurant_id:** identifies the restaurant (a slug, e.g. `demo`). It is NOT a secret
  and NOT the OpenTable RID. Dev seeds two restaurants: `demo` and `acme`.
- **Health (no auth):** `GET /healthz` → `{"status":"ok",...}`.

---

# The exact API contract (answers your 7 questions)

## 1 & 2. The endpoints
- **Check availability:** `POST /v1/reservations/availability`
- **Create/book:** `POST /v1/reservations/book`
- (Also available, OpenTable-backing unverified: `POST /v1/reservations/modify`,
  `POST /v1/reservations/cancel`.)

## 3. Headers
| Header | On | Required? | Purpose |
|---|---|---|---|
| `Authorization: Bearer <token>` | all `/v1/*` | **required** | Switchboard's internal token (NOT an OpenTable key) |
| `Content-Type: application/json` | all POSTs | **required** | JSON body |
| `Idempotency-Key: <id>` | **book / modify / cancel** | **required** | A stable id per booking attempt; **reuse it on retry** so a dropped line can't double-book |
| `X-Deadline-Ms: <int>` | any | optional (recommended) | Your hard deadline in ms. A human is on the line — set e.g. `2000`. On exceed you get a fast `timeout`/`requires_human`, never a hang |
| `X-Request-ID: <id>` | any | optional (recommended) | Correlation id (use the call id); echoed back in the body + `X-Request-ID` header |

> You do **not** send the OpenTable RID or any `X-Restaurant-ID` header — `restaurant_id`
> in the body is the single source of truth.

## 4. Request payloads (what nico sends)

**Availability** — `POST /v1/reservations/availability`
```json
{
  "restaurant_id": "demo",
  "date": "2026-07-01",
  "time": "19:00",
  "party_size": 4
}
```

**Book** — `POST /v1/reservations/book` (header `Idempotency-Key: <uuid-per-attempt>`)
```json
{
  "restaurant_id": "demo",
  "date": "2026-07-01",
  "time": "19:00",
  "party_size": 4,
  "customer": {
    "name": "John Smith",
    "phone": "+14155551212",
    "email": "john@example.com"
  },
  "notes": "Customer requested outdoor seating if available."
}
```

## 5. Response format (what nico gets back — the SAME envelope on every response)
```jsonc
{
  "ok": true,                  // true ONLY for a definitive, trustworthy answer
  "state": "available",        // the normalized result — THE field you switch on
  "data": { ... },             // payload on success; null on failure
  "error": {                   // present on failure; null on success
    "code": "timeout",
    "message": "...",          // safe text — do NOT branch on it
    "retryable": true
  },
  "source": "reservations",
  "latency_ms": 12,
  "mock": true,
  "request_id": "…"
}
```

**Availability success** (`data`): `{ "state": "available"|"unavailable", "slots": [ { "date": "2026-07-01", "time": "19:00", "party_size": 4 } ] }`
- `state":"available"` ⇒ the requested time is bookable. `slots` lists open times that
  day (the requested one if open, plus alternatives to offer).

**Book success** (`data`): `{ "state": "confirmed", "confirmation_id": "MOCK-DEMO-…" }`
- A `confirmation_id` appears **only** here.

## 6. Required vs optional fields
**Availability:** `restaurant_id` ✅, `date` ✅ (`YYYY-MM-DD`), `time` ✅ (`HH:MM`, 24-hour,
restaurant-local), `party_size` ✅ (1–100; `>12` returns `unavailable`).
**Book:** all of the above ✅, plus `customer.name` ✅, `customer.phone` ✅,
`customer.email` ⛔ optional, `notes` ⛔ optional, and the `Idempotency-Key` header ✅.

## 7. Error handling — branch on `state` (or `error.code`), never on `ok` alone
| state / code | HTTP | retryable | What nico should do / say |
|---|---|---|---|
| `available` | 200 | — | "Yes, that time is available." |
| `unavailable` | 200 (avail) / 409 (book) | no | "That time isn't available — I have 7:30 or 8:00, would either work?" (use `slots`) |
| `confirmed` | 200 | — | "Okay, great — you're booked, confirmation <id>." |
| `timeout` | 504 | yes (reads) | "I'm having trouble reaching the system — let me try once more / take a message." Retry a READ once; for a write see `requires_human`. |
| `rate_limited` | 429 | yes (backoff) | brief hold / retry shortly |
| `auth_error` | 502 | no | system issue → take a message + alert ops (do not retry) |
| `unknown` | 502 | yes | treat as failure → offer callback / take a message |
| `requires_human` | 409 | no | **ambiguous write** — the booking may or may not have gone through. **Do NOT silently retry.** Tell the customer you'll confirm and have a human verify. |
| `bad_request` | 400 | no | nico sent a bad/missing field — fix the payload (bug) |
| `unauthorized` | 401 | no | bad token — config/ops issue |
| `not_found` | 404 | no | unknown `restaurant_id`, or unknown/!your `confirmation_id` |

**Booking idempotency (important for a phone agent):** generate ONE `Idempotency-Key`
(a UUID) the moment the customer says "yes, book it," and send it on the book request.
If the call drops / you must retry **that same booking**, send the **same** key — you'll
get the same `confirmation_id` back, never a second reservation. A different booking gets
a new key.

## Example error responses
Booking the same slot after it filled (the availability≠booked race), HTTP 409:
```json
{ "ok": false, "state": "unavailable", "data": null,
  "error": { "code": "unavailable", "message": "The requested slot is no longer available.", "retryable": false },
  "source": "reservations", "latency_ms": 8, "mock": true, "request_id": "…" }
```
A booking that exceeded the deadline (ambiguous), HTTP 409:
```json
{ "ok": false, "state": "requires_human", "data": null,
  "error": { "code": "requires_human", "message": "The write exceeded its deadline and may or may not have completed; reconcile before retrying.", "retryable": false },
  "source": "reservations", "latency_ms": 1950, "mock": true, "request_id": "…" }
```

## End-to-end (matches the voice flow)
```bash
TOKEN="<SWITCHBOARD_TOKEN>"; BASE="<BASE_URL>"
# 1) "let me check availability"
curl -s -X POST $BASE/v1/reservations/availability \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H 'X-Deadline-Ms: 2000' \
  -d '{"restaurant_id":"demo","date":"2026-07-01","time":"19:00","party_size":4}'
# 2) customer confirms -> "okay, great" -> book (note the Idempotency-Key)
curl -s -X POST $BASE/v1/reservations/book \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: call-7f3a-booking-1' -H 'X-Deadline-Ms: 2500' \
  -d '{"restaurant_id":"demo","date":"2026-07-01","time":"19:00","party_size":4,
       "customer":{"name":"John Smith","phone":"+14155551212"}}'
```

## Testing against the dummy data (mock mode)
The mock is **stateful** (book consumes a slot; availability then reflects it). Seeded
for `demo` and `acme` on **2026-07-01**: `19:00` (capacity 10), **`19:30` (capacity 1 —
use to force the race)**, `20:00` (capacity 5). Scenarios you can trigger yourself:
`confirmed` (book 19:00), the race → `unavailable` (book 19:30 twice with different keys),
`not_found` (book/cancel a made-up confirmation_id), `unavailable` (party_size > 12),
`bad_request` (omit a field or the Idempotency-Key header), `unauthorized` (omit token).
The `timeout`/`auth_error`/`rate_limited`/`unknown` paths need server-side injection —
ask the operator, or request a mock-only `X-Mock-Scenario` header and we'll add it.

The committed **`spec/openapi.json`** is the source of truth — import it into Postman or
generate a client; flag any place it disagrees with reality.

## What to send back to the Switchboard team (so we build the RIGHT contract)
1. Confirm you can run availability → book against `demo` and handle every state above.
2. **What's missing/awkward for a voice agent:** Do you need a **GET reservation lookup**
   (status by confirmation_id) or "list my reservations"? Do you need to send the
   **caller's phone automatically** as `customer.phone`? Any field you need
   (e.g. seating preference as structured data vs `notes`)? Do you want the
   `X-Mock-Scenario` header to self-test failures? Is `date`+`time` right, or would a
   single ISO datetime be easier for your NLU output?
3. Any contract ambiguity. We will confirm OpenTable's real fields once partner approval
   lands and adjust — so tell us now what nico needs and we converge before go-live.
