# Switchboard — course-correction from an architecture review (apply to the in-progress build)

Paste this to the building agent. These also live in `architecture.md` under "Build discipline."

1. **Build the concrete capability, NOT an abstract gateway.** Implement `Reservation Availability v1`
   first, then `Reservation Booking v1`, as capability-shaped endpoints. Do NOT build a generic
   `POST /integrations/{name}/invoke` or a plugin/registry framework — each future integration adds its
   OWN capability-shaped endpoints. Keep the whole service small enough that deleting it wouldn't feel
   tragic. No platform ambitions yet.
2. **Normalized result states.** Every real-time endpoint returns exactly one of:
   `available, unavailable, unknown, timeout, auth_error, rate_limited, requires_human`. Never leak a raw
   vendor error or a false confirmation in the response.
3. **The caller owns the fallback, not the gateway.** Return the normalized state; the calling agent
   decides what to say/do. Partial failures must never become false confidence.
4. **Deadline propagation, per-endpoint budgets.** Accept a hard deadline from the caller, propagate it to
   the upstream call, return `timeout` if exceeded. Budgets are PER-ENDPOINT (live availability ~1.5s;
   async scrape jobs get a looser budget) — not one flat number.
5. **Idempotent writes + the availability≠booked race.** Every write takes an idempotency key. A slot can
   vanish between checking availability and booking — confirm atomically and return
   `requires_human`/`unavailable` on a race; never report a false success.
6. **Correlation IDs across logs** — one request ID threading the caller's logs and the gateway's logs.
7. **Hostile, prod-safe mocks.** Mocks must exercise timeouts, slow responses, malformed data, auth
   failure, no-availability, and booking-failure-after-apparent-availability — not just the happy path.
   Make mock mode impossible to use in production without an explicit environment/tenant flag.
8. **Decouple logically, not physically.** Bind to 127.0.0.1 or a Unix socket + a simple internal auth
   token; keep the gateway version-locked with its callers in one deployment for now — don't go remote yet.
