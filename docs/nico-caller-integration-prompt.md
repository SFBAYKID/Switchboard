# Prompt for the nico-project agent — integrating with Switchboard (Reservations API)

> Paste everything below the line to the Claude working on the **nico** project. It is
> the integration brief + the contract + the task. (Two values are environment-specific
> and will be given to you by the operator: the **base URL** and the **bearer token** —
> placeholders are marked `<...>`.)

---

You are integrating the **nico** agent with **Switchboard**, an internal HTTP API
gateway that owns third‑party integrations. Your first integration is **Reservations**
(OpenTable, behind the gateway). Today Switchboard runs in **mock mode**: it returns
fake‑but‑contract‑shaped reservation data through the real code path, so you can build
and fully test the nico ↔ Switchboard loop now, before OpenTable partner access exists.
When access lands, **nothing on your side changes** — same endpoints, same request
bodies, same response shape; only the response's `mock` flag flips from `true` to
`false`.

**Your job has two parts:**
1. Build nico's Switchboard **client** + a small demo program that calls the
   reservations endpoints and **mutates data** (availability → book → modify → cancel),
   handling **every** normalized result state.
2. **Tell the Switchboard team what you need.** If you need an endpoint, field, or
   behavior that isn't in the contract below (e.g. a GET to look up a reservation),
   say so — we'll build the right thing together. Do not work around a missing
   capability silently.

## Ground rules (important)
- **You are just an HTTP client.** You never hold OpenTable credentials or call
  OpenTable directly. You send Switchboard a bearer token + a `tenant` identifier;
  Switchboard resolves the tenant's upstream credentials itself.
- **You own the fallback, not Switchboard.** Switchboard returns a *normalized state*
  fast; deciding what nico does with it (retry, take a message, escalate to a human)
  is your orchestration. A non‑success state must **never** be treated as success.
- **Never assume a write succeeded.** A booking is confirmed only when you get
  `state: "confirmed"` with a `confirmation_id`. Anything else is not a booking.

## Connection
- **Base URL (dev):** `<BASE_URL>` (e.g. `http://127.0.0.1:8080` — localhost, internal only)
- **Auth:** every `/v1/...` request must send `Authorization: Bearer <SWITCHBOARD_TOKEN>`.
  A missing/invalid token returns a `401` envelope (code `unauthorized`).
- **Tenant:** pass `tenant` in the request body. It's an identifier, not a secret. For
  dev the seeded tenants are **`demo`** and **`acme`**.
- **Health (no auth):** `GET /healthz` → `{"status":"ok",...}`. `GET /v1` → version/info.

## The uniform response envelope (EVERY response — success and failure)
```jsonc
{
  "ok": true,                 // true ONLY for a definitive, trustworthy answer
  "state": "available",       // the normalized result state (see table); null on system endpoints
  "data": { ... },            // payload on success; null on failure
  "error": {                  // present on failure; null on success
    "code": "timeout",
    "message": "...",         // safe text; do NOT branch on it
    "retryable": true
  },
  "source": "reservations",   // which module answered ("gateway" for auth/validation faults)
  "latency_ms": 12,
  "mock": true,               // true while in mock mode; flips to false at go-live
  "request_id": "..."         // correlation id; also returned in the X-Request-ID header
}
```
**Branch on `state` (or `error.code`), never on `ok` alone, and never on `message`.**

## Normalized states you MUST handle
| state | ok | HTTP | meaning → what nico should do |
|---|---|---|---|
| `available` | true | 200 | slots returned → offer them |
| `unavailable` | true (avail) / false (book) | 200 / 409 | no availability / slot gone → offer alternatives |
| `confirmed` | true | 200 | booking made → `data.confirmation_id` is real |
| `modified` / `cancelled` | true | 200 | the write applied |
| `timeout` | false | 504 | upstream too slow → safe to retry (reads only) |
| `rate_limited` | false | 429 | back off and retry later |
| `auth_error` | false | 502 | tenant's upstream creds rejected → escalate (don't retry) |
| `unknown` | false | 502 | upstream errored/unusable → treat as failure |
| `requires_human` | false | 409 | **ambiguous write** (may or may not have happened) → **do NOT blind‑retry; reconcile/escalate** |
| (gateway) `bad_request` | false | 400 | your request was malformed |
| (gateway) `unauthorized` | false | 401 | bad/missing bearer token |
| (gateway) `not_found` | false | 404 | unknown tenant, or unknown/!your reservation |
| (gateway) `internal_error` | false | 500 | gateway bug → fail safe |

## Endpoints (all POST, JSON in/out)

### Availability — `POST /v1/reservations/availability` (real‑time)
Request:
```json
{ "tenant": "demo", "party_size": 2, "datetime": "2026-07-01T19:00:00" }
```
Success `data`:
```json
{ "state": "available", "slots": [ { "time": "2026-07-01T19:00:00", "party_size": 2 } ] }
```
`party_size` 1–100; `> 12` returns `unavailable` (mirrors "large parties can't book online").

### Book — `POST /v1/reservations/book` (consequential write)
Request (`idempotency_key` is **REQUIRED**):
```json
{ "tenant": "demo", "name": "Ada Lovelace", "party_size": 2,
  "datetime": "2026-07-01T19:00:00", "idempotency_key": "nico-<stable-uuid>" }
```
Success `data`:
```json
{ "state": "confirmed", "confirmation_id": "MOCK-DEMO-…" }
```

### Modify — `POST /v1/reservations/modify` (write)
```json
{ "tenant": "demo", "confirmation_id": "MOCK-DEMO-…",
  "party_size": 4, "datetime": "2026-07-01T20:00:00", "idempotency_key": "nico-<uuid>" }
```
Success `data`: `{ "state": "modified", "confirmation_id": "MOCK-DEMO-…" }`. Unknown/foreign id → `404 not_found`.

### Cancel — `POST /v1/reservations/cancel` (write)
```json
{ "tenant": "demo", "confirmation_id": "MOCK-DEMO-…", "idempotency_key": "nico-<uuid>" }
```
Success `data`: `{ "state": "cancelled", "confirmation_id": "MOCK-DEMO-…" }`. Cancelling twice is idempotent (still `cancelled`). Unknown/foreign id → `404 not_found`.

## Idempotency (writes) — get this right
- **Every write requires `idempotency_key`.** Generate ONE stable key per logical
  action (e.g. per user's "book this slot" intent) and **reuse it on every retry** of
  that same action. Same key ⇒ same result, no double‑book.
- On `timeout`/`requires_human` for a **write**, the write may or may not have landed.
  **Do not blind‑retry.** Reconcile (re‑check state / escalate). A retry is only safe
  with the *same* idempotency_key.

## Deadlines (optional but recommended)
- Send `X-Deadline-Ms: <int>` — your hard budget in ms. Switchboard answers within
  `min(your deadline, its per‑endpoint budget)`; if the upstream is slower you get a
  `timeout` (read) or `requires_human` (write) **fast**, never a hang. (A deadline at
  or below ~50ms leaves no time for the upstream and will usually time out.)

## Correlation
- Send `X-Request-ID: <id>` so nico's logs and Switchboard's logs line up. If you
  don't, Switchboard generates one. It's always returned (header + `request_id`).

## Testing against the dummy data (mock mode)
The mock is **stateful and seeded from a JSON file**, so it behaves like a real
reservation system. Seeded for `demo` and `acme` on **2026‑07‑01**:
- `19:00:00` capacity 10 — general booking
- `19:30:00` **capacity 1** — use this to trigger the **availability≠booked race**
- `20:00:00` capacity 5

Scenarios you can trigger **yourself** today:
- **confirmed**: book `2026-07-01T19:00:00`.
- **availability reflects bookings**: book the `19:30` slot, then call availability — it's gone.
- **unavailable (race)**: book `19:30` twice with **different** idempotency_keys → 2nd is `unavailable` (409).
- **unavailable (availability)**: availability with `party_size` `> 12`.
- **not_found**: modify/cancel a made‑up `confirmation_id` (or one from another tenant).
- **unauthorized / bad_request**: omit the token / send `party_size: 0` or omit `idempotency_key`.

Scenarios that need server‑side injection (ask the operator, or tell us and we'll add
a per‑request test header): **timeout, auth_error, rate_limited, unknown**. These are
real upstream conditions the operator can force via env (`MOCK_RESERVATIONS_FAIL`,
`MOCK_RESERVATIONS_DELAY_MS`). If self‑service for these would help you build nico's
degrade paths, say so — we can expose a mock‑only `X-Mock-Scenario` header.

## Reference: minimal Python client
```python
import httpx, uuid

BASE = "<BASE_URL>"            # e.g. http://127.0.0.1:8080
TOKEN = "<SWITCHBOARD_TOKEN>"  # given to you by the operator
H = {"Authorization": f"Bearer {TOKEN}"}

def availability(tenant, party_size, when, deadline_ms=1500):
    r = httpx.post(f"{BASE}/v1/reservations/availability",
                   headers={**H, "X-Deadline-Ms": str(deadline_ms),
                            "X-Request-ID": uuid.uuid4().hex},
                   json={"tenant": tenant, "party_size": party_size, "datetime": when})
    return r.json()  # branch on body["state"]

def book(tenant, name, party_size, when, idem):
    r = httpx.post(f"{BASE}/v1/reservations/book", headers=H,
                   json={"tenant": tenant, "name": name, "party_size": party_size,
                         "datetime": when, "idempotency_key": idem})
    body = r.json()
    if body["state"] == "confirmed":
        return body["data"]["confirmation_id"]
    # unavailable / requires_human / timeout / auth_error / rate_limited / unknown
    raise RuntimeError(f"not booked: {body['state']} ({body['error']})")
```

## What to deliver back to the Switchboard team
1. A short note confirming you can run the full loop (availability → book → modify →
   cancel) against `demo`, handling every state in the table.
2. **A list of anything missing or awkward for nico**: endpoints you need that don't
   exist (e.g. `GET /v1/reservations/{confirmation_id}` to look up status, or a
   list‑my‑reservations), fields you need in the payloads, states you can't currently
   exercise, or a request for the `X-Mock-Scenario` header.
3. Any contract ambiguity you hit. The committed OpenAPI spec
   (`spec/openapi.json`) is the source of truth — you can import it into Postman or
   generate a client from it; flag any place the spec and reality disagree.

Build to the contract above, prove the loop against the dummy data, and send back your
gaps so we converge on the right endpoints before OpenTable goes live.
