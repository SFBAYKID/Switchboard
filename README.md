# Switchboard — the Integration Gateway

Switchboard is a standalone, lightweight **internal HTTP API service** (FastAPI). Its
single job: own the connections to third-party APIs (OpenTable first; Stripe, website
scraping, and others later) and return their data to internal calling agents over
**one clean, versioned, token-gated internal contract** wrapped in a **uniform
response envelope**. Callers stay lightweight — Switchboard holds the integration
clients and the per-tenant credentials; callers just ask.

It is **not** an LLM agent, **not** the source of truth (the upstreams are — it may
cache, never owns), and **not** where business logic lives (callers decide; the
gateway connects and executes). It is **not** an audio/voice system.

> **Standalone isolation (non-negotiable).** Switchboard inherits nothing. No
> pre-existing infrastructure, deploy targets, SSH aliases, credentials, services, or
> environments are assumed — it defines and creates its own. It holds only its OWN
> secrets in its OWN `.env`. Every support agent operates only within Switchboard's
> own footprint.

## Status

**BUILT + verified (against the mock backend):** the internal API skeleton, the
uniform envelope, the bearer-token gate, per-tenant credential resolution, the
latency-budget/deadline machinery with graceful fallback, and the **reservations**
module in **mock mode** (`availability`, `book`, `modify`, `cancel`). The OpenAPI
spec is generated and committed. 47 tests pass; `mypy` is clean.

**Seams (plan — NOT built):** the real OpenTable client (swap-in after partner
approval, docs-verified per Rule 2), and the `payments` (Stripe) and `website`
(crawl) modules. Each future integration adds its OWN capability-shaped endpoints.

## The contract

### Uniform response envelope (every response)

```jsonc
{
  "ok": true,                  // true only for a DEFINITIVE, trustworthy answer
  "state": "available",        // normalized result state (real-time endpoints); null otherwise
  "data": { ... },             // payload on success; null on failure
  "error": {                   // structured error on failure; null on success
    "code": "timeout",
    "message": "…",            // safe; never a secret or raw vendor error
    "retryable": true
  },
  "source": "reservations",    // which module/backend answered ("gateway" for gateway faults)
  "latency_ms": 0,             // measured (mostly the upstream round trip)
  "mock": true,                // true only when a mock backend served this
  "request_id": "…"            // correlation id (also in the X-Request-ID header)
}
```

### Normalized result states (review #2/#3)

Every real-time endpoint resolves to **exactly one** normalized `state`, so a caller
switches on a single field and decides its own fallback (the caller owns the
fallback, not the gateway):

| state            | `ok`  | HTTP | meaning |
|------------------|-------|------|---------|
| `available`      | true  | 200  | availability found (slots present) |
| `unavailable`    | true* | 200* | no availability (`*`booking: false / 409 — slot gone) |
| `confirmed`      | true  | 200  | booking confirmed (confirmation id present) |
| `modified` / `cancelled` | true | 200 | write applied |
| `timeout`        | false | 504  | upstream exceeded the deadline |
| `rate_limited`   | false | 429  | upstream rate-limited |
| `auth_error`     | false | 502  | the tenant's upstream credential was rejected |
| `unknown`        | false | 502  | upstream errored / returned unusable data |
| `requires_human` | false | 409  | ambiguous (e.g. a write whose result was lost) |

Gateway-level faults carry **no** `state` (it is `null`): `bad_request` (400),
`unauthorized` (401, the internal token), `not_found` (404, unknown tenant — fail
closed), `internal_error` (500). A raw vendor error or a false confirmation is never
returned.

### Endpoints

| Method & path | Purpose | Class |
|---|---|---|
| `POST /v1/reservations/availability` | Reservation Availability v1 | real-time (budgeted) |
| `POST /v1/reservations/book` | Reservation Booking v1 | write (idempotent, race-safe) |
| `POST /v1/reservations/modify` | Modify a booking | write (idempotent) |
| `POST /v1/reservations/cancel` | Cancel a booking | write (idempotent) |
| `GET /healthz` (+ `/health` alias) | Liveness (no auth, no secrets) | system |
| `GET /v1` | Contract/version info | system |

Request body uses `restaurant_id` (the gateway identifier, **not** the OpenTable
RID/key), split `date` (`YYYY-MM-DD`) + `time` (`HH:MM`), and a `customer` object on
booking. See `spec/openapi.json` (the source of truth) or `nico-caller-integration-prompt.md`.

### Request headers

- `Authorization: Bearer <token>` — **required** on every `/v1/reservations/*` call.
- `Idempotency-Key: <id>` — **required on writes** (`book`/`modify`/`cancel`); a stable
  key per logical write, reused on retry, so a retry can't double-act (review #5).
- `X-Deadline-Ms: <int>` — **optional** caller hard deadline (ms). Effective deadline is
  `min(this, the per-endpoint budget)`; on exceed a read returns `state=timeout` and a
  write `state=requires_human` within budget (review #4).
- `X-Request-ID: <token>` — **optional** correlation id; echoed back (else generated).

> **Verification (Rule 2):** the reservations contract is Switchboard's OWN normalized
> shape. The OpenTable backing of `book`/`modify`/`cancel` and `customer.email`/`notes`
> is **unverified** (OpenTable's API is partner-gated) — see architecture.md "OpenTable
> integration — verification status". Everything is mock today (`mock:true`).

## Run it

```bash
# 1. Create Switchboard's OWN .env (gitignored) from the template:
cp .env.example .env
#    then set SWITCHBOARD_API_TOKEN and at least one
#    SWITCHBOARD_OPENTABLE__<TENANT>__API_KEY. Generate a token with:
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Install (into a virtualenv):
pip install -e ".[dev]"

# 3. Run the service (internal-only; binds to localhost — review #8):
uvicorn switchboard.api.main:app --host 127.0.0.1 --port 8080

# 4. Try it:
TOKEN=$(grep '^SWITCHBOARD_API_TOKEN=' .env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8080/v1/reservations/availability \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"restaurant_id":"demo","date":"2026-07-01","time":"19:00","party_size":2}'
```

## Develop

```bash
pytest                              # run the test suite
mypy                                # static type-check gate (Rule 12)
python scripts/export_openapi.py    # regenerate spec/openapi.json (commit the result)
```

`spec/openapi.json` is the committed source of truth for the contract; a test
(`test_openapi_parity.py`) fails if it drifts from the running app. Import it into
Postman to test (see the project docs).

## Mock-first, and the real swap

`RESERVATIONS_BACKEND=mock` (default) serves fake-but-contract-shaped data so the full
loop is testable now. When OpenTable partner approval lands, implement
`OpenTableReservationsBackend` (docs-verified — Rule 2) and flip
`RESERVATIONS_BACKEND=opentable`. Callers change nothing; only `mock` flips to false.

Mock mode is **refused in production** unless `SWITCHBOARD_ALLOW_MOCK_IN_PROD=true`
is set explicitly (review #7). The mock is hostile-by-design — it can inject
timeouts, auth failures, rate limiting, malformed data, no-availability, and the
booking-after-availability race — so callers exercise their degrade paths early.

## Layout

```
switchboard/
  core/          envelope, errors+normalized states, config, credential resolver, dispatch
  integrations/
    reservations/  models, interface (Protocol), backend_mock, backend_opentable (seam), backends
  api/           auth gate, timing+correlation middleware, error handlers, routes/, main
scripts/         export_openapi.py
spec/            openapi.json (committed source of truth)
tests/           the suite (envelope, auth, mock, hostile outcomes, deadlines, isolation, …)
.claude/agents/  architectural-critic, qa-end-2-end-tester, droplet-ops-guardian
```

## Support agents

Configured under `.claude/agents/` per the project setup docs, each scoped strictly
to Switchboard's own footprint:

- **architectural-critic** — pressure-tests designs before they ship.
- **qa-end-2-end-tester** — adversarial verification against the mock; honest about
  what is gated on the real OpenTable sandbox.
- **droplet-ops-guardian** — the sole authorized path for any future server op;
  **dormant** while running locally against mocks, mandatory once a real deploy
  exists.

See `CLAUDE.md` and `architecture.md` (the architectural source of truth) for the
full rules and design.
