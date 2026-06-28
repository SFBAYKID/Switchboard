# Switchboard — Architecture (source of truth)

Switchboard is a lightweight internal **middleware API service** — the "Integration
Gateway." Its single job is to connect to third-party APIs (OpenTable, Stripe, website
scraping, and whatever comes next) and return their data to internal callers over one clean,
versioned internal API. This document is the architectural **source of truth**; the project's
`CLAUDE.md` should point here. Everything forward-looking is marked as a **plan**, not a fact.

> **Status (pre-implementation, drafted 2026-06-28):** this is a design document for a
> brand-new project. **Nothing here has been built or run yet.** Every "the gateway does X"
> statement below describes the intended design, not verified behavior. When code lands, each
> section should be updated to separate **BUILT + verified** from **plan**. Do not read any
> claim in this file as "it works" — per the engineering discipline below, only something
> actually run-and-passed may be called done.

---

## Isolation: standalone project (load-bearing — read first)

**Switchboard is a brand-new, standalone project. Assume NO pre-existing infrastructure.**
This is non-negotiable and appears at the top of every Switchboard doc on purpose:

- Switchboard assumes **no pre-existing deploy targets, SSH aliases, credentials, services,
  environments, file paths, or deploy commands**. Everything operational is defined and created
  fresh for Switchboard. If project-specific configuration is needed, **create it** rather than
  assuming it already exists.
- Switchboard is an **HTTP API service (FastAPI-style request/response)**. Its entire surface is
  a versioned HTTP contract — typed request models in, a uniform JSON envelope out. There is no
  audio pipeline, no streaming media path, and no real-time transport machinery in this design.
- **Callers are simply clients of Switchboard's internal API** — internal calling agents, one
  client among future agents. That is the entire relationship. Switchboard exposes a contract;
  callers use it. Switchboard never reaches *into* a caller, holds a caller's secrets, or knows a
  caller's internals.
- Switchboard has its **OWN (to-be-defined) infrastructure**: its own service unit, its own
  deploy path, its own secret store, its own bearer tokens, its own ops process — all scoped to
  Switchboard and defined fresh here, assuming nothing pre-existing. Where a concrete target is
  not yet decided, it is marked **TBD / plan**, never borrowed.

Any time an action in this project could reach outside Switchboard's own footprint, the correct
move is to **stop and refuse**. Operate **only** within Switchboard's own footprint.

---

## Purpose

Every agent that wants restaurant availability, a payment, or a scraped page should NOT grow
its own copy of that integration — its credentials, its client library, its retry logic, its
upstream quirks. Switchboard is the **single home for all third-party integrations** so that:

- **Callers stay lightweight.** A caller sends one authenticated HTTP request and gets back a
  uniform envelope. It never imports a vendor SDK, never holds a vendor key, never learns a
  vendor's pagination rules.
- **Integrations are written once.** OpenTable is implemented in exactly one place. When the
  next agent needs reservations, it reuses the same endpoint — no second implementation.
- **The contract is stable.** Upstream APIs change; callers should not churn when they do.
  Switchboard absorbs upstream change behind a versioned internal contract.

What Switchboard **is**: a deterministic API wrapper, a per-tenant credential resolver, an
optional short-lived cache, and a mock-capable test surface.

What Switchboard **is NOT**: it is **not an LLM agent** (it has no model and makes no
decisions), it is **not the source of truth** (the external systems are — it may cache, never
own), and it is **not where business logic lives** (callers orchestrate; Switchboard just
connects).

---

## Data flow

```
   Caller  (any internal calling agent — just an HTTP client)
       │
       │  HTTP POST /v1/<integration>/<action>
       │  Authorization: Bearer <switchboard-token>          (localhost hop — sub-ms; see "Transport")
       ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │  Switchboard API   (FastAPI + uvicorn)                                          │
   │    1. Token gate ............... 401 if the bearer token is missing/invalid     │
   │    2. Validate request body .... typed request models (party_size, datetime…)  │
   │    3. Resolve credentials ...... (tenant + integration) → upstream creds        │
   │                                  from Switchboard's OWN secret store (env)      │
   │    4. Dispatch to the module ... uniform internal interface (one per integration)│
   │    5. Enforce latency budget ... upstream timeout < budget on real-time calls    │
   │    6. Wrap in the envelope ..... measure latency_ms, set source + mock           │
   └──────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
   Integration module  (uniform interface; e.g. `reservations`)
       ├── mock backend   ── fake but realistic data — the DEFAULT until real access lands
       └── real backend   ── e.g. an OpenTable client (plan) — swapped in later; contract unchanged
       │
       │  outbound HTTPS to the third-party API   ◄── THIS hop is where the real latency lives
       ▼
   Third-party API  (OpenTable / Stripe / a target website / …)  = the SOURCE OF TRUTH
       │
       ▼
   Uniform response envelope  { ok, data, error, source, latency_ms, mock }  ──► back to caller
```

The shape of the hop is the whole point: a caller's interaction with Switchboard is identical
whether the mock or the real backend answers, and identical across integrations.

---

## The module-per-integration design (the core structural choice)

Switchboard is organized as **one module per integration**, each implementing a **uniform
internal interface**. This is the load-bearing decision that lets the system grow without
turning into a tangle.

**The rule: adding Stripe never touches OpenTable.** Each integration lives in its own
package, owns its own request/response models, its own mock backend, and its own real backend.
The API layer dispatches to a module through a small, typed interface; it does not know vendor
specifics. New integration = new package + a route registration. Existing modules are not
edited, re-tested, or re-deployed because a sibling was added.

**Shape of a module (proposed layout — plan):**

```
switchboard/
  api/                 # FastAPI app, routing, the token gate, envelope wrapping, latency timing
  core/                # shared, vendor-agnostic plumbing:
    envelope.py        #   the response envelope model + helpers
    credentials.py     #   per-tenant credential resolver (reads Switchboard's secret store)
    config.py          #   fail-loud config validation at startup (Rule: fail fast, not silently)
    errors.py          #   structured error types + the timeout/budget machinery
  integrations/
    reservations/      # FIRST module — OpenTable (mock-first)
      interface.py     #   the typed Protocol/ABC every reservations backend implements
      models.py        #   AvailabilityRequest/Result, BookingRequest/Result, …
      backend_mock.py  #   MockReservationsBackend — fake data, DEFAULT
      backend_opentable.py  # OpenTableReservationsBackend — real client (PLAN, swapped in later)
    payments/          # FUTURE module — Stripe (plan; not built)
    website/           # FUTURE module — scraping/crawl (plan; not built)
```

**The uniform internal interface (typed).** Each module exposes a backend interface — a Python
`Protocol` (or ABC) with precisely typed methods. For reservations (illustrative — exact
signatures land with the code, and the upstream-specific fields are confirmed against real
OpenTable docs before the real backend is written, per the engineering discipline):

```python
class ReservationsBackend(Protocol):
    async def availability(self, req: AvailabilityRequest) -> AvailabilityResult: ...
    async def book(self,         req: BookingRequest)      -> BookingResult: ...
    async def modify(self,       req: ModifyRequest)       -> BookingResult: ...
    async def cancel(self,       req: CancelRequest)       -> CancelResult: ...
```

Two implementations satisfy that interface — `MockReservationsBackend` and (later)
`OpenTableReservationsBackend`. The API layer holds a reference to *the interface*, never to a
concrete vendor class, so it is blind to which backend is live. Type annotations are precise
end to end (request/response models, the interface methods, config constants); `Any` is avoided
and, where a vendor object's type is genuinely unknown, that is stated in a comment rather than
papered over — a wrong shape on an integration boundary fails quietly, so the types are a real
guardrail, not decoration.

**Backend selection is config, not code.** Which backend a module uses is chosen per
integration via configuration (e.g. `RESERVATIONS_BACKEND = "mock" | "opentable"`), validated
at startup. Flipping a single integration from mock to real does not touch any other module.

---

## The internal API (v1)

The internal contract is **versioned** under a `/v1` prefix. The intent (plan) is that an
**OpenAPI spec is the source of truth** for the contract, so callers can generate/validate
against it and so the shapes stay stable as upstreams change. The `/v1` prefix means a future
breaking change ships as `/v2` without stranding existing callers.

### The uniform response envelope (on EVERY response)

Every endpoint — success or failure, mock or real — returns the same top-level envelope. This
is what lets a caller write one handler and have it work across integrations and across the
mock→real swap.

| Field        | Type                       | Meaning                                                                 |
|--------------|----------------------------|-------------------------------------------------------------------------|
| `ok`         | `bool`                     | `true` only for a DEFINITIVE, trustworthy answer; `false` otherwise.    |
| `state`      | `string \| null`           | Normalized result state on real-time endpoints (see below); `null` on system endpoints. |
| `data`       | `object \| null`           | The integration-specific payload when `ok`; `null` otherwise.           |
| `error`      | `object \| null`           | A structured error when not `ok`; `null` otherwise. See below.          |
| `source`     | `string`                   | Which module/backend answered (e.g. `"reservations"`, `"gateway"`).     |
| `latency_ms` | `integer`                  | Measured time Switchboard spent producing the answer (mostly upstream). |
| `mock`       | `bool`                     | `true` if a mock backend served this response; `false` for real.       |
| `request_id` | `string`                   | Correlation id (also returned in the `X-Request-ID` header).            |

The **`error`** object is structured and stable:
`{ code: string, message: string, retryable: bool }`. A caller branches on `ok` and the
normalized `state` (or `error.code` / `error.retryable`) — never by string-matching a message.

**Normalized result states (real-time endpoints).** Every real-time endpoint resolves to exactly
one of: `available`, `unavailable`, `confirmed`, `modified`, `cancelled`, `unknown`, `timeout`,
`auth_error`, `rate_limited`, `requires_human`. `ok` is `true` only for the definitive successes
(availability answered; a real confirmation/modify/cancel); the rest are `ok=false`. Gateway-level
faults carry `state=null` with `error.code ∈ { bad_request, unauthorized, not_found, internal_error }`.

The **`mock`** flag is deliberately first-class: a caller (and a human reading logs) can always
tell at a glance whether a confirmation came from fake data or a real upstream, which matters
during the OpenTable approval window when both modes coexist across integrations.

### Endpoints (v1 — first module + sketched future modules)

Reservations (the first module — mock-first; **real-time** unless noted). The body uses
`restaurant_id` (the gateway identifier, NOT the OpenTable RID/key), split `date`+`time`, and a
`customer` object on booking. Writes require an `Idempotency-Key` header; an optional
`X-Deadline-Ms` header carries the caller's hard deadline:

- `POST /v1/reservations/availability` — body `{ restaurant_id, date, time, party_size }` →
  `data: { state, slots: [{ date, time, party_size }] }`. **Real-time** (deadline-budgeted).
- `POST /v1/reservations/book` — body `{ restaurant_id, date, time, party_size, customer:{ name,
  phone, email? }, notes? }` + `Idempotency-Key` header → `data: { state: "confirmed",
  confirmation_id }`. A **write** (consequential).
- `POST /v1/reservations/modify` — body `{ restaurant_id, confirmation_id, date?, time?,
  party_size? }` + `Idempotency-Key`. A **write**.
- `POST /v1/reservations/cancel` — body `{ restaurant_id, confirmation_id }` + `Idempotency-Key`.
  A **write**.

> **Verification status (Rule 1/2):** these are Switchboard's OWN normalized shapes. The OpenTable
> backing of `book`/`modify`/`cancel` and of the `customer.email`/`notes` fields is **UNVERIFIED**
> (OpenTable's API is partner-gated — see "OpenTable integration — verification status" below).

Operational endpoints:

- `GET /healthz` — liveness/readiness (no auth required; returns no secrets). **Plan.**
- `GET /v1` — contract/version info. **Plan.**

Sketched future modules (**plan — NOT built; listed only to show the contract generalizes**):

- `POST /v1/website/crawl` — body `{ tenant, url }` → `data: { job_id }`. **Async** (returns a
  job handle immediately; see "Data posture" for how results are delivered — and note the
  result delivery is to *the requesting caller*, defined by Switchboard's own callback/polling
  contract, never coupled to any specific caller's internal storage).
- `POST /v1/payments/...` — Stripe. **Later.**

**`tenant` is an identifier, never a credential.** Callers pass *which tenant* the request is
for; they never pass that tenant's upstream API keys. Switchboard resolves the secret itself
(next section). This is what keeps secrets out of every caller.

---

## Mock-first, and the real-swap

**Every integration ships a mock backend, and mock is the default.** The mock returns
fake-but-realistic data shaped exactly like the real response, behind the exact same internal
interface and the exact same envelope. This is not a throwaway stub — it is a first-class
backend that lets the **entire loop be built, tested, and demoed before real upstream access
exists.**

This directly de-risks the OpenTable timeline: OpenTable partner approval is expected to take
~3 weeks, and that wait blocks *go-live*, not *build*. With the mock, a caller integrates
against `/v1/reservations/*` today, exercises availability/booking end to end, and is fully
wired. When approval lands, the work is to implement `OpenTableReservationsBackend` against the
real API and flip `RESERVATIONS_BACKEND` to `opentable`. **Callers change nothing** — same
endpoints, same request bodies, same envelope; only the `mock` flag flips to `false`. The
internal contract is the invariant; the backend is the variable.

Because the mock is meant to harden the contract (not just smoke-test it), it should model the
shapes that real life produces — no availability, partial availability, an upstream error, and
a slow response that trips the latency budget — so callers exercise their degrade paths against
the mock before the real backend ever exists.

---

## Per-tenant credential resolution

Switchboard is multi-tenant at the credential layer: tenant A's OpenTable account is not tenant
B's. The flow:

1. The caller includes a `tenant` identifier in the request body (an identifier only).
2. Switchboard's **credential resolver** (`core/credentials.py`) maps `(tenant, integration)`
   to that tenant's upstream credentials, read from **Switchboard's own secret store**.
3. The selected backend receives the resolved credentials and makes the upstream call.

**Secrets live in Switchboard's environment, never in callers and never in code.** For the MVP
the secret store is environment variables (loaded at startup, validated to exist, failing loudly
if a required one is missing). A more capable secret store (e.g. an encrypted vault) is a later
upgrade behind the same resolver interface — **plan**. The proposed env convention namespaces by
integration and tenant, e.g. `SWITCHBOARD_OPENTABLE__<TENANT>__API_KEY` (exact scheme finalized
with the code). Secrets are **never logged**, never echoed, and never included in any envelope or
error message; the full config/environment is never printed.

The payoff: a caller holds exactly one Switchboard bearer token and a tenant name. It never sees
an OpenTable key, a Stripe key, or any upstream credential — so a compromised or chatty caller
cannot leak upstream secrets it was never given.

---

## Transport: token-gated localhost

**Switchboard binds to localhost (`127.0.0.1`) and is reached over a same-host hop (plan).**
The deployment intent (plan) is that Switchboard runs as its own service on its own deployment
host and that callers on the same host reach it over localhost. The same-host hop is
**sub-millisecond** and is *not* where latency comes from — the upstream third-party API is (see
"Latency"). Binding to localhost rather than a public interface means the API is not exposed to
the internet; any internet-facing exposure (a reverse proxy terminating TLS) is out of scope for
the MVP and would be a deliberate, separately-designed step. **Plan.**

**Every request must carry a valid bearer token.** Switchboard authenticates each request with
an `Authorization: Bearer <token>` header; a missing or invalid token returns `401` with an
`unauthorized` error envelope. The token(s) are **Switchboard's own secrets**, held in
Switchboard's environment — not shared with, derived from, or borrowed from anything pre-existing.
(Per-caller tokens, so individual callers can be rotated/revoked independently, are a reasonable
extension — **plan**.) The token gate is the authentication boundary; localhost binding is the
network boundary; together they keep the gateway internal-only.

This bearer-token-over-localhost pattern is Switchboard's own design, defined here from scratch.
It deliberately does **not** import, reference, or depend on any pre-existing auth code, tokens,
or transport.

---

## Latency: the hard budget + fallback (real-time endpoints)

Some endpoints are called **on a live, latency-sensitive path** (e.g. a caller asking for
reservation availability on a real-time endpoint where a human may be waiting for a response).
These carry a **hard latency budget** of **~1.5s** (configurable; the exact number is tuned per
endpoint).

Mechanism:

- For a real-time endpoint, Switchboard sets an **upstream timeout strictly below the budget**,
  so it can always answer the caller *within* the budget — either with the upstream result or
  with a clean timeout envelope.
- On timeout (or upstream error), Switchboard returns `ok = false` with a structured
  `error` (e.g. `code = "upstream_timeout"`, `retryable = true`) and the measured `latency_ms`.
  **Switchboard never hangs the caller** waiting on a slow upstream.
- **The caller owns the user-facing fallback.** Switchboard's job is to return a fast, honest
  answer (success or a structured failure) within budget; *deciding what to do* with a failure
  (take a message, offer a callback, retry later) is the caller's orchestration, not
  Switchboard's. Switchboard is deterministic plumbing — it reports, it does not decide.

**Async endpoints are explicitly off the budget.** A crawl (`/v1/website/crawl`) returns a
`job_id` immediately and does its slow work in the background; nothing about it sits on a
real-time path, so the ~1.5s budget does not apply.

Honesty note (engineering discipline): an endpoint is "fast" only when measured. The localhost
hop and the Python framework are **not** meaningful latency levers; the upstream third-party API
is. `latency_ms` exists precisely so this is observed rather than guessed, and so future tuning
targets the real cost (the upstream round-trip), not the wrong thing.

---

## Data posture

**Switchboard is mostly a stateless wrapper. The external systems are the source of truth.**

- **No system-of-record state.** Switchboard does not own reservations, payments, or page
  content. It reads from and writes to the upstream, which holds the truth. If Switchboard's
  process is wiped and restarted, no canonical data is lost, because it held none.
- **Optional, short-lived cache (plan).** Read-mostly, idempotent results (e.g. availability)
  may be cached briefly behind a short TTL purely to shave repeat upstream round-trips. The
  cache is an optimization, never a source of truth, and it is **read-only-shaped**: it never
  serves stale data for a **write** and never *is* the answer of record.
- **Writes are never cached, and must be safe to retry.** Consequential actions (`book`,
  `modify`, `cancel`, and future `charge`) go straight to the upstream. Idempotency keys on
  writes (so a retried `book` cannot double-book) are part of the write design — **plan**, and
  confirmed against each vendor's idempotency support before the real backend ships.
- **The only legitimate persistence is operational, not domain.** Async jobs (the crawl
  `job_id` → status/result handle) need a small amount of tracking state. That is bookkeeping
  about *Switchboard's own jobs*, not third-party domain data, and it lives in Switchboard's own
  store (mechanism TBD — in-memory for the MVP is acceptable; a small persistent store later).
  **Plan.** No databases, tables, or large stores beyond this are in scope for the MVP.
- **Destructive operations are gated.** Consistent with the engineering discipline, no
  destructive op (dropping a store, wiping a cache namespace, deleting job records) happens
  without explicit confirmation, and where reasonable a backup is taken first. There is, by
  design, very little here *to* destroy — which is the point of the stateless posture.

---

## First module: reservations (OpenTable), mock-first

The first and only module built initially is **`reservations`**, backing the
`/v1/reservations/*` endpoints, **mock-first**:

- **Now:** `MockReservationsBackend` returns fake availability and bookings shaped exactly like
  the real responses, behind the `ReservationsBackend` interface and the standard envelope
  (`mock = true`). Callers integrate and exercise the full availability→book→modify→cancel loop
  immediately — no waiting on OpenTable.
- **When OpenTable partner approval lands (plan):** implement `OpenTableReservationsBackend`
  against the **real OpenTable API**. Before writing it, the exact OpenTable endpoints,
  auth scheme, request/response shapes, and idempotency support are **confirmed against current
  official OpenTable documentation** — not guessed from memory — because a single wrong field on
  an integration boundary fails quietly. Then flip `RESERVATIONS_BACKEND` to `opentable`.
- **Caller impact of the swap: none.** Same endpoints, same request bodies, same envelope; only
  `mock` flips to `false`. The ~3-week approval window blocks go-live, never build.

`payments` (Stripe) and `website` (crawl) are **sketched only** to prove the design
generalizes; they are **plan — not built**, and when built they are added as new modules that do
not touch `reservations`.

---

## Running it (proposed canonical commands — plan)

These are the intended commands; they are recorded here as the single place the run/test
commands will live once code exists. They describe the planned shape, not verified behavior.

- **Run the service (dev):** a single uvicorn entrypoint serving the FastAPI app on localhost,
  e.g. `uvicorn switchboard.api.main:app --host 127.0.0.1 --port <PORT>` — exact module path and
  port finalized with the code. **Plan.**
- **Run the tests:** `pytest` from the repo root. **Plan.**
- **Type-check:** the configured static type checker over the whole package (the codebase is
  fully type-annotated, so this is a real gate, not a formality). **Plan.**
- **Config:** an `.env.example` is checked in listing every required variable with **no real
  values**; the real `.env` is never committed; `core/config.py` validates required vars at
  startup and fails loudly if any are missing. **Plan.**

---

## Deployment & ops (Switchboard's own — plan)

Switchboard will eventually run as its **own service**, on its **own deployment host** — with its
**own** service unit, **own** deploy path, **own** secret store, and **own** ops process, all
scoped to Switchboard. The concrete targets (service-unit name, deploy directory, login/scope)
are **TBD** and will be defined fresh for this project; they are **created**, not assumed to
already exist. Proposed (plan) naming would be Switchboard-scoped (e.g. a `switchboard`-prefixed
service and deploy path), confirmed when the deploy is designed.

A strict isolation discipline governs all Switchboard operations: operate **only** inside
Switchboard's own footprint; **never** read, list, modify, or interact with anything outside that
footprint — data, files, processes, environments, secrets, or proxy config that are not
Switchboard's own; if an action could reach outside Switchboard's own footprint, **stop and
refuse**. Switchboard's deploys and operational changes go through Switchboard's own ops process
within that footprint — **plan**, defined when deployment is built. None of this references or
reuses any pre-existing ops tooling, logins, or commands; Switchboard creates its own.

---

## Security summary

- **Localhost bind + bearer-token gate** — not internet-exposed; every request authenticated
  (`401` on a bad/missing token). (Both **plan** until built.)
- **Secrets only in Switchboard's environment** — never in callers, never in code, never in
  logs, never in an envelope/error. `.env` is gitignored; `.env.example` is the committed,
  value-free template; config fails loudly on a missing required var.
- **`tenant` is an identifier, not a credential** — callers never hold upstream keys.
- **Structured errors, no leakage** — error envelopes carry a stable `code` and a safe message;
  they never embed secrets or raw upstream credentials.
- **Writes are deliberate** — consequential actions (`book`/`charge`) are explicit endpoints,
  retry-safe via idempotency keys (plan), and never auto-fired by Switchboard on its own;
  Switchboard executes, callers decide.

---

## Engineering discipline (applies to all Switchboard work)

The universal quality bar, reoriented to this project:

- **Never fabricate.** No invented endpoints, vendor field names, command outputs, test results,
  or "it works." On uncertainty: "I don't know" / "I cannot verify that" / "it did not run."
- **Verify external API specifics before writing them.** Every upstream's exact endpoints, auth,
  request/response shapes, and idempotency behavior (OpenTable first, then Stripe, etc.) are
  confirmed against current official docs before the real backend is written — never reconstructed
  from memory. If the docs can't be reached, stop and say which specific facts need verifying.
- **Comment heavily.** Every file opens with a header explaining its purpose; every non-obvious
  block — especially credential resolution, the latency/timeout machinery, and any vendor-shape
  mapping — gets an explanatory comment for a reader who hasn't seen this plumbing.
- **Precise type annotations throughout.** Function/method signatures, module constants, and
  non-obvious locals are typed; precise types over `Any`; when a vendor object's type is genuinely
  unknown, say so in a comment rather than hiding it behind `Any`. Integration boundaries fail
  quietly, so the types are a real guardrail.
- **Test honesty + discipline.** Unit, contract, and regression tests for anything that builds up
  and tears down its own state; the mock backends make the full loop testable without real upstream
  access. Never claim a test (or type-check) passed unless it genuinely ran and passed; separate
  "verified by running" from "reasoned about." Don't ship untested work.
- **No destructive ops without confirmation** — and back up first where reasonable (see "Data
  posture"; there is little to destroy by design).
- **Commit/push honesty.** Stage with explicit `git add <path>` only (never `-A`/`.`, so a `.env`
  never slips in); descriptive messages; show `git diff --stat` and the unpushed log before a push;
  report the real result — never claim "pushed" if it failed.

---

## OpenTable integration — verification status (Rule 2; read before writing the real client)

**Reference this section before implementing or describing the OpenTable backend.** It records
what is actually verifiable today so we never present unverified vendor specifics as fact.

**[fact / cited 2026-06] OpenTable has NO open/public API.** It is partner/affiliate-gated:
you must apply, execute an agreement, and be approved; the detailed per-API documentation
(endpoints, auth, fields, error codes) is only available AFTER approval. Public sources:
- https://docs.opentable.com/ (the API docs — content gated)
- https://dev.opentable.com/ (developer portal)
- https://www.opentable.com/restaurant-solutions/api-partners/ and its `/faqs/` and
  `/become-a-partner/` and `/terms-and-conditions/` pages
- https://support.opentable.com/s/article/What-is-OpenTable-s-Consumer-API (gated)

**What we therefore CANNOT verify today (treat as UNKNOWN, do not invent):**
- exact base host + endpoint paths for availability / create / modify / cancel;
- whether server-side create/modify/cancel exist for our partner tier **at all** (non-authoritative
  sources suggest some affiliate tiers are reservation-*link* only — must be confirmed);
- the auth scheme (the code assumes RID + API key; it may be `client_id`/OAuth);
- the idempotency mechanism + header name (may be `X-Request-Id`, not `Idempotency-Key`);
- which guest fields OpenTable accepts/returns (does `email` / `notes` exist?);
- error codes, rate-limit semantics, pagination.

**Consequence for the gateway contract:** the caller-facing reservations contract is **Switchboard's
OWN normalized abstraction**, not a description of OpenTable. The `book`/`modify`/`cancel` operations
and the `customer.email`/`notes` fields are exposed as our normalization with their OpenTable backing
**unverified**; the mock serves them (flagged `mock:true`) and the real client is an unimplemented
seam. When approval lands, confirm each item above against the real docs and **adjust the gateway
contract if OpenTable cannot back it** (e.g. drop `modify`/`cancel` if the tier is link-only).

**Facts to capture at approval (fill in, then implement):** base host; endpoint paths; auth scheme;
real identifier (RID vs other); idempotency header; accepted guest/notes fields; error + rate-limit
semantics. Until every one is confirmed, `RESERVATIONS_BACKEND` stays `mock`.

---

## Out of scope / future modules (plan only — one line each)

- **Payments (Stripe)** — a `payments` module; same uniform interface + mock-first. NOT BUILT.
- **Website crawl/scrape** — a `website` module; async `job_id`, result delivered back to the
  requesting caller via Switchboard's own callback/polling contract. NOT BUILT.
- **Persistent secret vault** — replace env-based secrets behind the same resolver. NOT BUILT.
- **Per-caller tokens + rotation** — finer-grained auth than a single shared token. NOT BUILT.
- **Result cache with real eviction** — beyond the optional short-TTL read cache. NOT BUILT.
- **Public exposure / reverse proxy** — Switchboard is localhost-internal in the MVP. NOT BUILT.

---

## Build discipline — review refinements (2026-06-28)

An independent architecture review confirmed the direction (a thin, boring, LOCAL integration boundary)
and added the following, which now govern the build:

- **Build the CAPABILITY, not an abstract gateway.** Start with concrete, capability-shaped endpoints —
  `Reservation Availability v1`, then `Reservation Booking v1` — NOT a generic integration framework.
  Each future integration adds its OWN capability-shaped endpoints. **NEVER** build a generic
  `POST /integrations/{name}/invoke` — that's a weak RPC tunnel whose contract goes muddy fast. Keep the
  whole service small enough that deleting it wouldn't feel tragic; no platform ambitions yet.
- **Normalized result states** (every real-time endpoint returns exactly one): `available`,
  `unavailable`, `unknown`, `timeout`, `auth_error`, `rate_limited`, `requires_human`. Callers branch on
  the state; the gateway never leaks a raw vendor error or a false confirmation.
- **The fallback policy is owned by the CALLER, not the gateway.** The gateway returns a normalized state
  (incl. `timeout`/`unknown`); the calling agent decides what to say/do. Partial failures must NEVER
  surface as false confidence in speech.
- **Deadline propagation, end-to-end.** The caller passes a hard deadline; the gateway propagates it to
  the upstream call and returns `timeout` if exceeded. Budgets are PER-ENDPOINT, not flat — a live
  availability check is ~1.5s; an async scrape is off the human-wait path and gets a looser budget.
- **Writes are idempotent.** Any write (e.g. booking) takes an idempotency key. Critically,
  **availability != booked** — a slot can vanish between the check and the commit, so the booking must
  confirm atomically and return `requires_human`/`unavailable` on a race, never a false success.
- **Correlation IDs across logs.** One request ID threads the caller's logs and the gateway's logs so a
  cross-service call is traceable end-to-end.
- **Hostile, prod-safe mocks.** Mocks must exercise the bad paths — timeouts, slow responses, malformed
  vendor data, auth failure, no availability, booking-failure-after-apparent-availability — not just the
  happy path. Mock mode must be impossible to use in production without an explicit environment/tenant flag.
- **Decouple logically, not physically (for now).** Same host: bind to 127.0.0.1 or a Unix socket + a
  simple internal auth token; keep the gateway and its callers version-locked in one deployment until
  there's real pressure to split hosts.
- **Design against these known risks:** the internal API drifting generic and losing domain meaning; mock
  behavior diverging from the real vendor; optimistic timeouts (especially scraping); the
  availability/booked race; the gateway becoming a credential honeypot; partial failures leaking as false
  confidence; operational tax outgrowing the integrations.
