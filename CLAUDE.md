# Operating Rules for Claude on Switchboard (Integration Gateway)

Read this file before doing anything else in this repo. These rules are
constraints, not preferences. Rule 1 (never fabricate) outranks every other
instinct, including the desire to appear finished.

Read everything in this repo's docs (this file, `architecture.md`, the charter,
the OpenAPI spec) BEFORE writing any code.

## What this project is

Switchboard is the **Integration Gateway**: a standalone, lightweight internal
middleware API service whose single job is connecting to third-party APIs
(OpenTable, Stripe, website scraping, and whatever comes next) and returning
their data to internal callers over one clean, versioned internal API.

Switchboard exists so that every calling agent stays **lightweight**: no agent
ever accretes integration clients, credentials, or upstream-API quirks it may not
use. The gateway owns the external connections; callers just ask.

What it IS / ISN'T (from the charter):
- **IS** a deterministic API wrapper, a per-tenant credential vault, an optional
  cache, and mock-capable.
- **IS NOT** an LLM agent (it runs no model), NOT the source of truth (the
  external systems are — Switchboard may cache, never owns), and NOT where
  business logic lives (the calling agent orchestrates and decides; the gateway
  just connects and executes).

Data flow: internal caller (an agent) → HTTP request with a bearer token →
Switchboard (FastAPI-style service) → the right per-tenant integration module →
third-party API (or its MOCK backend) → uniform response envelope back to the
caller.

Switchboard is an **HTTP API service**, NOT a real-time audio pipeline. There is
no voice, no audio codec, no media-stream WebSocket, no speech model in this
project. Strip any such assumptions on sight.

`architecture.md` is the architectural source of truth (modules, the internal
contract, latency budget, fallback, seams). The OpenAPI spec is the source of
truth for the internal API shape.

---

## ISOLATION — Switchboard is a brand-new, standalone project (non-negotiable)

Switchboard is a **separate, self-contained project and tenant** with its **own
(to-be-defined) infrastructure**. Assume NO pre-existing infrastructure, deploy
targets, SSH aliases, credentials, services, environments, paths, or operational
habits — define and create Switchboard's OWN. If project-specific configuration is
needed, create it rather than assuming it already exists. Operate ONLY within
Switchboard's own footprint.

Concretely, in this repo and from every agent operating here:
- **No pre-assumed SSH, deploy commands, hosts, services, or file paths.** Do not
  assume that a scoped login, service name, host, deploy directory, systemd unit,
  or nginx vhost already exists to borrow. Switchboard gets its OWN deploy target,
  OWN service unit, OWN paths, OWN access — all defined and created for THIS
  project. If you need one, create it; never assume one is already there.
- **No borrowed internals.** No audio/voice/realtime/media-stream details, no
  speech-model event shapes, no conversational-agent logic, no personas or prompts.
  None of it is relevant to an HTTP integration gateway; if it appears, it is a
  copy-paste mistake — remove it.
- **Switchboard's OWN secrets only.** Switchboard holds its OWN secrets in its OWN
  `.env` / credential vault. It must never read, import, or depend on secrets from
  outside its own footprint. (Notably: a calling agent must never hand its
  integration credentials to Switchboard ad hoc, and Switchboard must never reach
  into a caller's secret store — see per-tenant credentials below.)
- **The gateway is the integration owner, the caller is not.** Calling agents
  NEVER hold integration credentials or external API clients. They call
  Switchboard; Switchboard connects. This separation is the whole point — keep it
  absolute.

Switchboard's ops guardian subagent operates ONLY within Switchboard's own
service, on Switchboard's own deploy target. It never touches anything outside
Switchboard's own footprint. If an action could reach outside that footprint, STOP
and refuse.

This isolation note is intentional and load-bearing — it must survive in every
doc this project produces.

---

## HARD RULES (non-negotiable)

### Rule 1 — Never fabricate
No invented APIs, function names, endpoint paths, request/response shapes, field
names, status codes, auth schemes, command outputs, test results, benchmarks, or
"it works" claims. If you have not actually run something, do not say you did. On
uncertainty, say "I don't know," "I cannot verify that," or "the test did not
run."

### Rule 2 — Verify external API specifics before writing them
Each integration module talks to a real third-party API (OpenTable, Stripe,
scraping targets, future ones). The exact endpoint paths, auth scheme (API key /
OAuth / bearer), request bodies, response shapes, pagination, rate limits, error
codes, and webhook formats MUST be confirmed against that vendor's current
official docs BEFORE writing the client. If you cannot access the docs, STOP and
tell the human which specific facts you need verified rather than writing
plausible-looking code from memory. A single wrong field name or auth header
fails — sometimes silently, sometimes by charging or booking incorrectly. The
real-integration clients are the highest-risk files in this project; treat them
that way.

The MOCK backends are exempt from vendor verification (they invent their own fake
data on purpose) — but a mock MUST mirror the SAME internal contract shape the
real client will return, so that swapping mock → real changes nothing for the
caller. Verify the contract shape even when the data is fake.

### Rule 3 — File size limits
No source file over 1000 lines (soft). Hard stop at 1500 lines — if any file
would exceed it, split it and explain the split. One module per integration keeps
files small naturally; these are guardrails, not targets.

### Rule 4 — Comment heavily
Every file opens with a header comment explaining its purpose. Every non-obvious
block — especially anything touching auth, credential resolution, the latency
budget/timeout logic, the error envelope, retries, or upstream-API quirks — gets
an explanatory comment. Assume the reader is smart but has not seen this
particular vendor's API or this gateway's plumbing before.

### Rule 5 — Speed is first-class, but be honest about it
The internal hop (caller → Switchboard) is localhost / same-host and effectively
free (sub-millisecond). **The real latency is the upstream third-party API.** Do
not claim a choice makes the gateway "fast" unless it is actually true, and do not
optimize the local hop while ignoring the upstream round-trip that dominates.
Document where latency actually comes from (upstream API processing, network to
the vendor, retries, cold caches) so future-you optimizes the right thing.

Real-time endpoints — those a caller invokes while a human may be waiting on the
line (e.g. reservation availability) — carry a **HARD latency budget (~1.5s,
confirm the exact number in `architecture.md`)**. On timeout or upstream error,
return the uniform error envelope promptly so the caller can degrade gracefully
(e.g. take-a-message) — NEVER hang the caller waiting on a slow upstream. Graceful
fallback is a feature, not an afterthought. (Async/job-style endpoints, e.g.
website crawl, are not on the human-waiting hot path and have their own,
looser budget — keep the two classes distinct.)

### Rule 6 — Label fact / assumption / recommendation / unverified
In any notes, comments, or messages to the human, distinguish what is verified
fact from assumption, recommendation, or unverified claim. Mark assumptions as
assumptions. "The OpenTable docs say X" requires you to have actually read it;
otherwise it is an assumption.

### Rule 7 — Good practices
Secrets only in `.env` / the credential vault (never committed). `.env.example` is
checked in and lists every required var with no real values. `config.py` (or
equivalent) validates required vars exist at startup and fails loudly if not.
Clear error handling on every external call and on the inbound API boundary. No
secrets in logs — never log tenant credentials, bearer tokens, API keys, or full
request bodies that may contain them; never print full settings or full `.env`
contents to the terminal or logs. Stage with explicit `git add <path>` only —
never `git add -A` or `git add .` (that is how a `.env` or a credential file gets
committed despite every other rule).

### Rule 8 — Test honesty and test discipline
Build unit and regression tests for features that build up and tear down their own
state. The mock-first design makes the full request→module→response loop testable
WITHOUT real vendor access — exercise it. Test the uniform envelope, the auth
gate, per-tenant credential resolution, timeout/fallback behavior, and the
mock↔real contract parity. Never claim a test passed unless it genuinely ran and
passed. Separate "verified by running" from "reasoned about but not executed." Do
not push a feature you have not tested yourself.

When the type checker or linter is part of verification, run it and report what
genuinely passed versus what only type-checks in theory. If no type checker is
configured, say so rather than implying one ran (Rule 11).

### Rule 9 — No destructive operations without confirmation
Never delete a database, drop a table, force-push, wipe storage/cache, remove the
virtualenv, or delete logs without explicit confirmation — and where reasonable,
back up first. This includes consequential UPSTREAM writes: a real `book`,
`cancel`, `modify`, or `charge` against a live vendor account is real-world
destructive/consequential. Such writes must be explicitly gated (by the calling
orchestrator and, where appropriate, a human approval step) — the gateway
executes, it does not decide. While developing, prefer mock mode so you never
accidentally book or charge for real.

### Rule 10 — Commit / push honesty
Commit with descriptive messages. Before any push, show `git diff --stat` and
`git log @{u}..HEAD --oneline`. Never claim "pushed" if the push failed.
Force-push and non-default-branch pushes require explicit approval.

### Rule 11 — Commit and push when work is complete (standing process)
When a unit of work is finished AND its tests pass, commit and push it to GitHub
(`origin`) as the standard close-out — don't leave finished work sitting
uncommitted. This is durable authorization for the routine commit+push to the
working branch; it does NOT loosen the safety rules:
- Stage with explicit `git add <path>` only — never `git add -A`/`.` (Rule 7).
- NEVER commit secrets or PII: `.env`, any credential/vault files, per-tenant
  config with real keys, cached upstream data that may contain customer PII — keep
  them gitignored.
- Show `git diff --stat` and `git log @{u}..HEAD --oneline` before pushing, and
  report the real result — never claim "pushed" if it failed (Rule 10).
- Force-push still requires explicit approval (Rule 10).
- If tests fail, do NOT commit — fix first, or say so.

### Rule 12 — Type annotations throughout the codebase
Add type annotations across the Python codebase — function/method signatures
(parameters and return types), module-level constants, and non-obvious local
variables. The goal is higher code quality and catching issues earlier through
static type checking rather than at runtime. This is especially valuable at the
integration boundary, where a wrong request/response shape can fail silently or
trigger a real upstream side effect (Rule 2). Model the uniform response envelope
and each integration's data shapes as explicit, precise types (e.g. dataclasses /
Pydantic models / TypedDicts) so mock and real backends are provably the same
shape. Prefer precise types over `Any`; when a vendor object's type is genuinely
unknown, say so in a comment rather than papering over it with `Any`.

### Rule 13 — Ops/deploys go through the ops guardian; tenant isolation is absolute
Switchboard runs as its OWN isolated tenant on its OWN infrastructure. Two
requirements, both non-negotiable and always-on:

1. **The ops guardian subagent is mandatory for every infrastructure operation**
   — deploy, update, restart, secret change, file ship, log inspection, or any
   operational change to Switchboard's running service. It runs plan → security
   review → run → verify. No agent — including the main loop — may push to, deploy
   to, ship files to, or run commands on the server directly; route it through the
   guardian. (Pushing code to GitHub with `git push origin …` is NOT a deploy and
   does not need the guardian; shipping to Switchboard's deploy directory or
   touching its running service DOES.)
2. **Tenant isolation is absolute.** Operate ONLY inside Switchboard's own tenant
   footprint, via Switchboard's own scoped login and own deploy target. NEVER use
   another tenant's login, NEVER read/list/inspect/modify/copy/interact with
   another tenant's data, files, processes, environment, secrets, service, or
   nginx vhost. If an action could reach outside Switchboard's own footprint,
   STOP and refuse. (See the ISOLATION section above — that is the spirit; this is
   the operational enforcement.)

Local development (running the service locally against mock backends) touches no
shared server and is exempt — but the instant any deploy/ops action on shared
infrastructure is needed, both requirements apply with no exceptions.

---

## Architecture in brief

- **One module per integration, uniform interface.** Each integration
  (`reservations` / OpenTable, `payments` / Stripe, `website` / scraping, …) is
  its own self-contained module behind a common interface. Adding Stripe never
  touches the OpenTable module. A module exposes the same operations whether it is
  in mock or real mode.
- **Mock-first.** Every integration ships a MOCK backend returning fake-but-
  contract-shaped data NOW, so callers integrate and the full loop is demoed
  BEFORE real vendor access exists. (This is exactly how OpenTable proceeds during
  its multi-week partner approval: build and test against the mock; swap to the
  real client when approval lands — the internal contract does not change, so the
  caller's code does not change.) Mode is config/per-tenant, never hardcoded.
- **Clean, versioned internal contract behind a token.** The internal API is
  versioned (`/v1/...`) and gated by bearer-token auth on every request. The
  OpenAPI spec is the contract's source of truth; stable shapes mean callers don't
  churn when an upstream API changes — the gateway absorbs the churn.
- **Uniform response envelope on every response:**
  `{ ok, data, error, source, latency_ms, mock }`. Callers branch on `ok`, read
  `data` on success, read the structured `error` on failure, and can see `source`,
  measured `latency_ms`, and whether the result came from a `mock` backend. One
  envelope across all modules — no per-integration response dialects.
- **Per-tenant credentials.** The gateway resolves the correct tenant's
  credentials for each call (tenant A's OpenTable account ≠ tenant B's). Secrets
  live in env / an encrypted vault, scoped per tenant, and NEVER leave the
  gateway. Credential resolution failures return the uniform error envelope, not a
  stack trace.
- **Hard latency budget + graceful fallback** on real-time endpoints, as in
  Rule 5: bound the wait, return a clean error envelope on timeout, let the caller
  degrade gracefully. Async/job endpoints (e.g. crawl) report progress via a job
  id rather than blocking.

### Internal API (v1 sketch — confirm against the OpenAPI spec before coding)
- `POST /v1/reservations/availability` `{tenant, party_size, datetime}` →
  `{available, slots[]}` (real-time, on the latency budget)
- `POST /v1/reservations/book` `{tenant, name, party_size, datetime}` →
  `{confirmation_id, status}` (consequential write — Rule 9)
- `POST /v1/reservations/modify` · `POST /v1/reservations/cancel`
  (consequential writes — Rule 9)
- `POST /v1/website/crawl` `{tenant, url}` → `{job_id}` (async)
- `POST /v1/payments/...` (Stripe — later; build the seam, not the feature yet)

### First module: reservations (OpenTable), mock-first
A `reservations` module with a MOCK backend returning fake availability/bookings
now. Swap the backend to the real OpenTable client when partner approval lands —
callers' requests are IDENTICAL either way because the internal contract does not
change. The approval wait blocks go-live, NOT the build.

---

## Coding standards (summary)
- Python, FastAPI-style HTTP service. Async where it touches the network; don't
  block the event loop on upstream calls.
- Type annotations everywhere (Rule 12); model the envelope and each integration's
  shapes as explicit types so mock and real are provably identical.
- Heavy comments at every non-obvious boundary (Rule 4), especially auth,
  credential resolution, timeouts/fallback, and vendor quirks.
- Config validated at startup, fail loudly on missing required vars (Rule 7).
- Tests for every module against its mock, plus the auth gate, envelope, per-tenant
  resolution, and timeout/fallback paths (Rule 8). Test honesty is mandatory.
- No secrets in logs or git; explicit `git add <path>` only (Rules 7, 11).

---

## Scope — build seams, not the future
- Build the gateway, the uniform envelope, the auth gate, per-tenant credential
  resolution, and the `reservations` module in MOCK mode first.
- Leave clean, clearly-marked seams for: the real OpenTable client (swap-in when
  approved), the Stripe `payments` module, the `website` crawl module, and an
  optional cache. Mark each seam; do NOT implement ahead of need.
- The gateway connects and executes; it does NOT decide. Business logic and the
  decision to perform a consequential write live with the calling agent's
  orchestrator (and a human approval where appropriate), never in Switchboard.

---

## Pointers
- `architecture.md` — architectural source of truth (modules, internal contract,
  latency budget, fallback, seams).
- The OpenAPI spec — source of truth for the internal API shape; keep it in sync
  with the code.
- The project charter (Integration Gateway charter) — purpose, principles, and
  boundaries.
- `.claude/agents/` — this project's subagents, including the ops guardian, which
  is MANDATORY for every deploy/op on Switchboard's own infrastructure and which
  never touches any other tenant (Rule 13). It is dormant only while running
  locally against mocks, never optional once a shared-infra op is needed.
