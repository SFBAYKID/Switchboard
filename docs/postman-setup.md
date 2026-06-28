# Switchboard — Postman Setup (API documentation + testing on the free tier)

_A doc for the **Switchboard** project (the Integration Gateway). Drafted 2026-06-28._
_Read the project charter (`integration-gateway-charter.md`) before this file._

---

## ABSOLUTE ISOLATION (non-negotiable)

Switchboard is a **brand-new, standalone project/tenant** with its **own (to-be-defined)
infrastructure**. This document, and everything it describes, assumes **no pre-existing**
infrastructure, deploy targets, SSH aliases, credentials, services, or environments:

- **No inherited knowledge or config.** Assume no existing servers, hosts, deploy targets, SSH
  aliases, file paths, systemd units, nginx vhosts, or secrets. If project-specific configuration is
  needed, **create Switchboard's own** rather than assuming it already exists.
- **Switchboard is an HTTP API service (FastAPI-style), not a real-time audio pipeline.** There are no
  audio/voice/realtime concerns here; this is a lightweight internal HTTP API.
- Every support agent and tool operates **only within Switchboard's own footprint**. All
  project-specific settings (base URLs, tokens, tenants, hostnames) are Switchboard's own and are
  defined here from scratch.

Where this doc references "the service," it means the **Switchboard Integration Gateway** running on
`localhost` during development.

---

## Universal quality discipline (carried into Switchboard)

These apply to everything in this doc and to anyone (human or agent) acting on it:

- **Never fabricate.** No invented Postman menu items, limits, prices, CLI flags, or "it works"
  claims. If something was not actually run or verified, say so.
- **Verify external specifics before relying on them.** Postman's plans/limits changed materially in
  March 2026 (see below) and vendor pages move. Re-check the **official** Postman docs/pricing in-app
  before acting on any number here; treat third-party blogs as secondary.
- **Comment heavily / write things down.** Collection descriptions, environment variable notes, and
  test scripts should explain *why*, not just *what*.
- **Precise types in test assertions.** When writing Postman/Newman test scripts, assert exact shapes
  and types of the response envelope — a wrong field fails silently otherwise.
- **Test honesty.** Never claim a Postman run or Newman run passed unless it genuinely ran and passed.
  Separate "verified by running" from "reasoned about but not executed."
- **No destructive ops without confirmation.** Don't delete shared collections/environments/specs or
  overwrite a teammate's workspace state without explicit confirmation; export a backup first.
- **Commit honesty.** The committed OpenAPI spec and any exported collection are versioned artifacts —
  commit with descriptive messages; never claim "pushed" if it failed.

> **Labeling convention (used throughout):** **[fact]** = verified against the cited source;
> **[assumption]** = our working assumption, stated so it can be challenged; **[recommendation]** =
> our advice; **[unverified]** = reported by a source we did not independently confirm.

---

## TL;DR recommendation

1. **The OpenAPI/Swagger spec is the single source of truth.** Keep `openapi.yaml` (or `.json`) in the
   Switchboard repo. Import it into Postman; never hand-build requests that drift from the spec.
   **[recommendation]**
2. **One Postman workspace ("Switchboard"), one imported spec, one generated collection** organized by
   spec **tags** (`reservations`, `website`, `payments`, `system`). **[recommendation]**
3. **Two (later three) environments** that differ only in `base_url` + token + the expected `mock`
   flag: `Switchboard — Local (mock)`, `Switchboard — Local (real)`, and later `Switchboard —
   Deployed`. **[recommendation]**
4. **Stay free by staying single-user and CI-first.** The Postman **Free plan is 1 user** as of March
   2026, but **Collection Runner and Mock Servers are now unlimited on all plans** (including Free).
   Run regression tests with **Newman** (open-source CLI) in CI — it consumes **zero** Postman quota.
   **[fact]** (see sources)
5. **Avoid the paid triggers:** extra seats (Team is **$19/user/mo**), scheduled **API Monitors**
   beyond the **1,000 requests/month** free cap, advanced governance, and >1 private Spec Hub API.
   **[fact]/[unverified]** as noted below.

---

## 1. The single source of truth: the OpenAPI spec

The charter (Principle #1) is explicit: **an OpenAPI spec is the source of truth; Postman is used to
test against it.** Postman is a *consumer* of the spec, not the place the contract is authored.

### Two honest ways to keep "spec = source of truth" with a FastAPI service

FastAPI **generates** an OpenAPI document from the code at runtime (commonly served at `/openapi.json`),
so the literal source of the JSON is the Python code. To keep the contract reviewable and stable
(charter: "stable shapes so calling agents don't churn"), pick one discipline and stick to it:

- **Code-first, spec-pinned (recommended for Switchboard). [recommendation]**
  Author endpoints + Pydantic models in FastAPI, then **export and commit** the generated spec to the
  repo (e.g. `spec/openapi.json`) as a checked-in artifact. A CI step regenerates it and **fails the
  build if the committed file is out of date** (a `git diff` check). The committed file is what gets
  imported into Postman and what reviewers diff in PRs. This makes contract changes explicit and
  visible without fighting FastAPI's code-first nature.

  Sketch (run from the repo root; the service must import without side effects):
  ```bash
  # Export FastAPI's generated spec to a committed artifact.
  python -c "import json, app.main as m; print(json.dumps(m.app.openapi(), indent=2))" \
      > spec/openapi.json
  # In CI, regenerate then assert no drift:
  git diff --exit-code spec/openapi.json   # non-zero exit = spec drifted, fail the build
  ```
  > **[unverified]** The exact import path (`app.main`) and app object name depend on Switchboard's
  > final layout — adjust to the real module. Confirm `app.openapi()` returns the expected document
  > before wiring CI.

- **Spec-first (alternative). [recommendation]**
  Hand-author `openapi.yaml` as the contract, review it in PRs, and generate/validate code against it.
  Heavier process; choose this only if multiple consumers need to negotiate the contract before code
  exists.

Either way: **one committed spec file in the repo is the artifact Postman imports.** Postman never
becomes the source of truth.

### Spec versions & formats Postman accepts

**[fact]** Postman's Spec Hub supports importing OpenAPI (2.0, 3.0, and 3.1), in **YAML or JSON**,
plus AsyncAPI/protobuf/GraphQL/Smithy. Import from a file/folder, a URL, pasted raw text, or a
connected Git repo (GitHub/Bitbucket/GitLab/Azure DevOps). (Sources: Postman import docs.)

---

## 2. Importing the spec into Postman (the flow)

**[fact]** Steps (current Postman UI per the official import docs):

1. In the left sidebar, click the **options (…) / Import** entry.
2. Choose the source: **upload a file/folder**, **enter a URL**, **paste raw** JSON/YAML, or
   **connect a Git repo**.
3. For an OpenAPI document, Postman offers an import method:
   - **Postman Collection** — generates a collection (folders, requests, response examples) from the
     spec, **without** creating a Spec Hub entry.
   - **Specification with Collection** — creates a **spec in Spec Hub** *and* a linked collection,
     and lets you keep the two **in sync** afterward.
4. Confirm; use the footer link ("Go to Specification" / "Go to Collection").

**[recommendation]** Use **Specification with Collection** so the spec lives in Spec Hub and the
collection can be **synced** when the spec changes — this directly serves "spec is the source of
truth." Caveat: on the Free plan this consumes your **single private Spec Hub API** slot (see §5). If
you'd rather keep the spec purely in Git and not spend that slot, use **Postman Collection** (import
only) and re-import on changes, or regenerate the collection in CI with the open-source converter
(§6).

> **[fact]** A collection generated from a spec can be **kept in sync** with that spec for OpenAPI
> 2.0/3.0/3.1 (per Postman's generate/sync docs).

---

## 3. Collection structure

Keep it boring and spec-driven. **[recommendation]**

```
Workspace: Switchboard
└── Collection: Switchboard Gateway v1            ← generated from spec/openapi.json
    ├── reservations/                              ← folder per spec tag
    │   ├── POST /v1/reservations/availability     (real-time; ~1.5s budget)
    │   ├── POST /v1/reservations/book
    │   ├── POST /v1/reservations/modify
    │   └── POST /v1/reservations/cancel
    ├── website/
    │   └── POST /v1/website/crawl                 (async → returns job_id)
    ├── payments/                                  ← Stripe, later (seam only)
    └── system/
        └── GET  /health                           (liveness / mode check)
```

- **Folder-per-tag:** when generating collections (UI or CLI), use the **Tags** folder strategy so the
  folder layout mirrors the spec's `tags`. Adding a future integration (e.g. Stripe) adds a tag/folder
  and never disturbs `reservations` — matching charter Principle #2. **[recommendation]**
- **Collection-level auth:** set the collection's Authorization to **Bearer Token =
  `{{switchboard_token}}`** so every request inherits it. This mirrors the charter's token-gated
  internal contract (Principle #5) without pasting the token into each request. **[recommendation]**
- **Saved example responses = living docs.** For each request, save at least one example response that
  matches the uniform envelope `{ ok, data, error, source, latency_ms, mock }`. These examples power
  Postman's auto-generated docs **and** can back a Postman Mock Server (§4). **[recommendation]**

---

## 4. Two meanings of "mock" — do not conflate them

This is the most common source of confusion for a mock-first project, so be explicit. **[recommendation]**

| | **Switchboard mock mode** (charter Principle #3) | **Postman Mock Server** (a Postman feature) |
|---|---|---|
| What it is | The FastAPI service running with the `reservations` module in **mock backend** mode, returning fake OpenTable data through the **real code path** | A Postman-hosted URL that replays **saved example responses** from the collection |
| Fidelity | High — it's the exact handler/middleware/envelope the calling agents will hit | Lower — static examples; no real logic, auth, or latency |
| Primary use | The default dev/test target until OpenTable approval lands | A stable stub URL when the service isn't running, or for sharing a contract with a consumer |
| Cost on Free | N/A (it's your code) | **[fact]** Mock servers are **unlimited on all plans** as of March 2026 |

**[recommendation]** Make **Switchboard mock mode** the primary test target — it exercises the real
code the calling agents will hit, so passing tests mean more. Treat the **Postman Mock Server** as an
optional convenience (e.g. a shareable stub, or to test caller-side code while the gateway is down).
Both are free; pick by fidelity, not by cost.

> **Setting up a Postman Mock Server (if you use one):** create it from the collection, pin example
> responses per request, then point an environment's `base_url` at the mock URL. Assert the envelope
> shape exactly as you would against the real service.

---

## 5. Environments (mock vs real)

Environments hold only what differs between targets; everything else stays in the collection.
**[recommendation]**

| Variable | `Switchboard — Local (mock)` | `Switchboard — Local (real)` | `Switchboard — Deployed` _(later)_ |
|---|---|---|---|
| `base_url` | `http://localhost:8080` | `http://localhost:8080` | _to be defined — Switchboard's own infra_ |
| `switchboard_token` | dev token (**secret** type) | dev token (**secret** type) | prod token (**secret** type) |
| `tenant` | `demo` | `demo` | real tenant slug |
| `expect_mock` | `true` | `false` | env-dependent |

Notes:

- **`base_url`** can be identical for local mock vs local real if the **service mode** is what
  toggles mock/real (charter: mock is a server-side backend mode). The environments then differ mainly
  by `expect_mock`, which drives the test assertion below. If instead you run a **Postman Mock Server**
  for the mock case, set that environment's `base_url` to the mock URL. **[assumption]** — confirm
  which toggle Switchboard implements.
- **Secrets:** mark `switchboard_token` as a **secret**-type variable and keep its value in the
  **current value** (local, not synced) field, or inject it at runtime via Newman (§6). **Never commit
  a real token**; never print it in logs. **[recommendation]**
- **Deployed env left intentionally undefined.** Switchboard's deploy target is its **own** to-be-
  defined infrastructure — define and create it as Switchboard's own when the time comes.
  **[recommendation]**

### A reusable test script (collection-level "Tests")

Assert the uniform envelope on every response. Put this at the **collection** level so it runs for all
requests. **[recommendation]**

```javascript
// Collection-level test: validate Switchboard's uniform response envelope.
// Envelope (charter): { ok, data, error, source, latency_ms, mock }
const body = pm.response.json();

pm.test("envelope has required fields with correct types", () => {
    pm.expect(body).to.be.an("object");
    pm.expect(body).to.have.property("ok").that.is.a("boolean");
    pm.expect(body).to.have.property("source").that.is.a("string");
    pm.expect(body).to.have.property("latency_ms").that.is.a("number");
    pm.expect(body).to.have.property("mock").that.is.a("boolean");
    // `data` present on success, `error` present on failure — exactly one is meaningful.
    if (body.ok) {
        pm.expect(body.data, "data on success").to.not.be.undefined;
    } else {
        pm.expect(body.error, "error on failure").to.not.be.undefined;
    }
});

// Tie the response to the active environment so mock/real can't be confused.
pm.test("mock flag matches the active environment", () => {
    const expectMock = pm.environment.get("expect_mock") === "true";
    pm.expect(body.mock).to.eql(expectMock);
});

// Real-time endpoints carry a hard latency budget (charter Principle #6, ~1.5s).
pm.test("real-time latency budget (availability)", () => {
    if (pm.request.url.getPath().endsWith("/v1/reservations/availability")) {
        pm.expect(body.latency_ms).to.be.below(1500);
    }
});
```

> **[recommendation]** Latency assertions on real (non-mock) runs measure the **upstream** API, which
> is the real risk per the charter — keep the threshold meaningful and only enforce it where a budget
> actually applies (real-time endpoints where a human may be waiting).

---

## 6. The free, quota-free CI loop (Newman + the open-source converter)

This is how Switchboard gets repeatable regression testing **without spending Postman quota or money**.
**[recommendation]**

- **`openapi2postmanv2`** (`openapi-to-postman`, official postmanlabs, open-source) converts the
  committed spec → a collection locally. **[fact]**
- **Newman** (official Postman CLI runner, open-source) runs a collection from the command line. Local
  Newman runs do **not** consume Postman cloud quota. **[fact]**

```bash
# 1) Convert the committed spec → a collection (folders by tag).
npx openapi-to-postmanv2 \
  -s spec/openapi.json \
  -o build/switchboard.postman_collection.json \
  -p -O folderStrategy=Tags

# 2) Run it against the locally-started service (mock mode), injecting the token at runtime.
#    --env-var keeps secrets out of any committed environment file.
npx newman run build/switchboard.postman_collection.json \
  --env-var "base_url=http://localhost:8080" \
  --env-var "switchboard_token=$SWITCHBOARD_TOKEN" \
  --env-var "tenant=demo" \
  --env-var "expect_mock=true"
```

> **[fact]** `openapi2postmanv2` also supports a `--sync` flag to update an existing collection from
> the spec (e.g. `-s spec.yaml --sync collection.json -o synced.json`). Use this if you maintain a
> long-lived collection JSON in the repo rather than regenerating it each run.

**CI recipe (Switchboard's own pipeline — provider-agnostic). [recommendation]**

1. Check out the repo (with `spec/openapi.json`).
2. Assert spec is not stale: regenerate from FastAPI and `git diff --exit-code spec/openapi.json` (§1).
3. Start the service in **mock mode** in the background; wait for `GET /health`.
4. Convert spec → collection with `openapi-to-postmanv2`.
5. Run `newman run …` with `expect_mock=true`; fail the job on any failed assertion.
6. (Optional) Export Newman's JSON/JUnit report as a build artifact.

Because steps 4–6 use only open-source CLIs against your own service, this loop is **$0 and consumes no
Postman cloud quota** regardless of plan. **[fact]/[recommendation]**

> **Alternative:** **Portman** (apideck, open-source) wraps OpenAPI→Postman conversion + generated
> contract/variation tests + Newman in one CLI for CI. Heavier than the two-step above; consider it
> only if you outgrow plain `openapi-to-postmanv2` + Newman. **[unverified]** — evaluate before adopting.

---

## 7. Free vs paid: what to use, what to avoid

**[fact]** **Postman plans changed in March 2026.** Two changes matter most here:
**(a)** the **Free plan is now 1 user** (free team collaboration was removed), and **(b)**
**Collection runs and Mock server usage are now unlimited on all plans**, including Free.
(Sources: Postman "About plans" docs + pricing page.)

> **Honesty note / data conflict [fact + unverified]:** Several third-party blogs (2026) still cite the
> **pre-March-2026** Free caps of **"25 collection runs/month"** and **"1,000 mock server
> requests/month."** Postman's **own** docs now state both are **unlimited on all plans**. Trust the
> official docs; treat those blog numbers as stale. Re-verify in-app before relying on either.

### Free plan — what you get (verify in-app)

| Capability | Free-plan status | Notes |
|---|---|---|
| Users / seats | **1 user** **[fact]** | No team collaboration on Free since March 2026 |
| API client + collections + environments | Included **[fact]** | Core of everything above |
| **Collection Runner** | **Unlimited** **[fact]** | In-app runs no longer capped |
| **Mock servers** (cloud & local) | **Unlimited** **[fact]** | Pricing page lists "Unlimited cloud & local mock servers" |
| **Spec Hub** private APIs | **1 private API** (+ public) **[unverified]** | Reported by third-party sources; confirm in-app. Affects "Specification with Collection" import (§2) |
| **API Monitoring** | **1,000 requests / month** **[fact]** | Scheduled monitors draw down this cap — use sparingly |
| AI credits | **50 / month** **[fact]** | Postbot/AI features; not needed for Switchboard's loop |
| Integrations | **Up to 5** **[fact]** | E.g. Git, CI hooks |
| Postman API calls | **10,000 / month** **[fact]** | Only if you script against Postman's own API |
| Collection recovery | **1 day** **[fact]** | Short window — export backups before risky edits (Rule: no destructive ops) |
| **Newman** (CLI) | **Free, open-source, no quota** **[fact]** | The backbone of the CI loop (§6) |

### Paid plans (per user / month) — what triggers a bill

**[fact]** (pricing page): **Solo $9**, **Team $19/user**, **Enterprise $49/user**.

Things that cost money / to avoid while staying free:

- **A second seat / shared team workspace with RBAC** → requires **Team ($19/user/mo)**. For a
  single-developer Switchboard, stay at 1 user. **[fact]/[recommendation]**
- **Heavy scheduled API Monitoring** beyond **1,000 requests/month** → drives upgrades. Use **Newman
  in CI/cron** instead (free, §6). **[recommendation]**
- **>1 private API in Spec Hub** → keep additional specs in Git, or import as collection-only.
  **[recommendation]**
- **Advanced governance / security rules, private packages, SSO/SCIM, longer recovery windows** →
  paid tiers; not needed for the MVP. **[fact]/[assumption]**

### How to stay on the free tier (checklist)

- [ ] **One user, one workspace.** Don't invite collaborators (that needs Team). **[recommendation]**
- [ ] **CI testing via Newman**, not scheduled Postman Monitors. **[recommendation]**
- [ ] **Spec in Git is the source of truth**; use at most the **1 free** Spec Hub private API (or none).
      **[recommendation]**
- [ ] **Keep integrations ≤ 5.** **[recommendation]**
- [ ] **Export a backup** (collection + environment JSON) before destructive edits — Free recovery is
      only **1 day**. **[recommendation]**
- [ ] **Never commit secrets**; inject `switchboard_token` at runtime (`--env-var`) and mark it secret
      in the app. **[recommendation]**
- [ ] **Re-verify limits in-app periodically** — Postman changed them in March 2026 and may again.
      **[recommendation]**

---

## 8. End-to-end workflow summary

1. Author endpoints in FastAPI; **export + commit** `spec/openapi.json` (CI fails on drift). **[recommendation]**
2. **Import** the committed spec into Postman as **Specification with Collection** (or collection-only
   to save the Spec Hub slot). **[recommendation]**
3. Organize the collection **by tag**; set **collection-level Bearer auth** = `{{switchboard_token}}`;
   save **example responses** matching the envelope. **[recommendation]**
4. Create environments **Local (mock)** / **Local (real)** (+ **Deployed** later) differing only in
   `base_url`, token, `tenant`, `expect_mock`. **[recommendation]**
5. Add the **collection-level envelope/latency tests** (§5). **[recommendation]**
6. In CI, **convert spec → collection** and run **Newman** against the service in **mock mode** — the
   $0, zero-quota regression loop (§6). **[recommendation]**
7. When OpenTable approval lands, **flip the service to real mode** and run the **Local (real)** env /
   `expect_mock=false`. The collection and contract are unchanged. **[recommendation]**

---

## Sources

- [About plans | Postman Docs](https://learning.postman.com/docs/billing/about-plans) — March 2026
  changes: Free plan = 1 user; **collection runs unlimited on all plans**; **mock server usage
  unlimited on all plans**.
- [Plans & Pricing | Postman API Platform](https://www.postman.com/pricing/) — Free plan inclusions
  (1 user, unlimited Collection Runner, unlimited mock servers, API Monitoring 1,000 requests/mo, 50
  AI credits/mo, up to 5 integrations, 10,000 Postman API calls/mo, 1-day collection recovery); paid
  pricing (Solo $9, Team $19/user, Enterprise $49/user per month).
- [Import an API specification | Postman Docs](https://learning.postman.com/docs/design-apis/specifications/import-a-specification)
  — import flow, sources (file/URL/raw/Git), "Postman Collection" vs "Specification with Collection".
- [Generate collections from your API specification | Postman Docs](https://learning.postman.com/docs/design-apis/specifications/generate-collections)
  — generating + keeping a collection in sync with the spec (OpenAPI 2.0/3.0/3.1).
- [Integrate Postman with OpenAPI | Postman Docs](https://learning.postman.com/docs/integrations/available-integrations/working-with-openAPI)
  — OpenAPI integration overview.
- [postmanlabs/openapi-to-postman (GitHub)](https://github.com/postmanlabs/openapi-to-postman) /
  [openapi-to-postmanv2 (npm)](https://www.npmjs.com/package/openapi-to-postmanv2) — open-source
  converter; CLI flags (`-s`, `-o`, `-p`, `-O folderStrategy=Tags`, `--sync`).
- [apideck-libraries/portman (GitHub)](https://github.com/apideck-libraries/portman) — alternative
  OpenAPI→Postman + Newman CI tool. **[unverified]** for Switchboard's needs.
- Third-party (secondary, used only to flag the stale pre-March-2026 caps and the "1 private Spec Hub
  API" figure — **verify in-app**): [apidog: Postman free plan limitations](https://apidog.com/blog/postman-free-vs-paid-comparison/),
  [costbench: Is Postman Free?](https://costbench.com/software/developer-tools/postman/free-plan/).

> **[fact]** Postman's plans and limits were changed by Postman in **March 2026**; figures here were
> checked against the official docs/pricing on **2026-06-28**. Re-verify in-app before relying on any
> specific number — vendor limits move.
