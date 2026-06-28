# Switchboard — Onboarding prompt (paste this to the new project's agent)

> You are starting work on **Switchboard**, a brand-new, standalone project. All the context you need is
> in this project's documentation folder.
>
> **Before you write any code:**
> 1. **Read every document in this folder, in order:** `README.md`, then `CLAUDE.md`, `architecture.md`,
>    `integration-gateway-charter.md`, `postman-setup.md`, and finally the three agent setup docs
>    (`agent-architectural-critic.md`, `agent-droplet-ops-guardian.md`, `agent-qa-end-2-end-tester.md`).
>    They define what you're building, how to build it, and how each supporting agent must behave.
> 2. **Configure each supporting agent specifically for this project**, exactly as its setup doc says.
> 3. **Assume nothing pre-exists.** Do not assume any existing infrastructure, servers, deployment
>    targets, SSH aliases, credentials, services, or environments. This project inherits nothing from
>    anywhere else.
> 4. **Build everything as a brand-new, standalone project.** If any project-specific configuration is
>    required — a service, a deploy target, a path, an env var, a credential — **create it for this
>    project** rather than assuming it exists. Ask me for any value only I can provide.
> 5. **Confirm before coding:** briefly summarize, in your own words, what Switchboard is, the standalone
>    isolation rule, and your first build target (the internal API skeleton + the mock reservations module
>    + the OpenAPI spec). Then proceed.
>
> Do not begin building until you've read all of the documentation.
