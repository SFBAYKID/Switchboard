# Integration Gateway — Project Charter (Switchboard)

_Switchboard is a brand-new, standalone project. Drafted 2026-06-28._

## Purpose
A standalone, lightweight internal HTTP API service — the SINGLE home for all third-party integrations
(OpenTable, Stripe, website scraping, and whatever comes next). Internal calling agents reach it over a
clean, versioned internal API; it owns the external connections. This keeps every calling agent
LIGHTWEIGHT — no caller ever accretes integrations it may not use.

Assume NO pre-existing infrastructure, deploy targets, SSH aliases, credentials, services, or
environments — define and create Switchboard's OWN. If project-specific configuration is needed, create it
rather than assuming it already exists. Operate ONLY within Switchboard's own footprint.

## What it IS / ISN'T
- **IS:** an HTTP API service (FastAPI-style); a deterministic API wrapper; a per-tenant credential vault;
  an optional cache; mock-capable.
- **IS NOT:** an LLM agent (no model); the source of truth (the external systems are — it may cache, never
  owns); the place business logic lives (the calling agents orchestrate; the gateway just connects).

## Principles
1. **Clean, versioned internal contract.** An OpenAPI spec is the source of truth; Postman to test.
   Stable shapes so calling agents don't churn when an upstream API changes.
2. **One module per integration, uniform interface.** Adding Stripe never touches the OpenTable module.
3. **Mock-first.** Every integration ships a MOCK mode (fake data) so a caller's flow is built + demoed
   BEFORE real API access — this is exactly how we proceed on OpenTable during the ~3-week approval.
4. **Per-tenant credentials.** The gateway resolves the right tenant's creds per call (tenant A's
   OpenTable account ≠ tenant B's). Secrets in env/encrypted — NEVER held by the calling agents.
5. **Token-gated, internal-only.** Caller↔gateway uses bearer-token auth; serve it on a private/loopback
   interface within Switchboard's own footprint (sub-ms hop — the real latency is the upstream API).
   Define and create Switchboard's own deploy target, service, and isolation rather than assuming any
   exist.
6. **Real-time discipline.** Real-time endpoints where a human may be waiting carry a HARD latency budget
   (~1.5s) + a uniform error envelope; on timeout/error the caller degrades gracefully (take-a-message),
   never blocks.

## Internal API (v1 sketch)
Uniform envelope on every response: `{ ok, data, error, source, latency_ms, mock }`.
- `POST /v1/reservations/availability` `{tenant, party_size, datetime}` → `{available, slots[]}`  (real-time)
- `POST /v1/reservations/book` `{tenant, name, party_size, datetime}` → `{confirmation_id, status}`
- `POST /v1/reservations/modify` · `POST /v1/reservations/cancel`
- `POST /v1/website/crawl` `{tenant, url}` → `{job_id}`  (async → returns results to the calling agent via its token)
- `POST /v1/payments/...`  (Stripe — later)

## First module: reservations (OpenTable), mock-first
- A `reservations` module with a MOCK backend returning fake availability/bookings NOW.
- Swap the backend to the real OpenTable client when the partner approval lands — the caller's calls are
  IDENTICAL either way (the internal contract doesn't change). The 3-week wait blocks go-live, not build.

## Boundaries with calling agents (so callers stay lean)
Calling agents request availability/book; the gateway answers. A calling agent NEVER holds integration
credentials or external API clients. Consequential writes (book / charge) stay gated by the calling
agent's orchestrator and its approval flow where appropriate — the gateway executes, it doesn't decide.
