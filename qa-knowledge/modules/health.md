# Module: Health

1 endpoint, `apps/api/src/health/health.controller.ts` (8 lines total — no service, no module-level dependency injection beyond the controller itself). Test: `health.controller.spec.ts` (2 cases).

Analyzed against commit `91e0447b` (see `overview.md`).

## `GET /health` (`health.controller.ts:7-9`)

- **Auth**: none. No guard, no DTO (no input at all).
- **Implementation**: `check()` is a plain synchronous method returning the literal `{ status: 'ok' }` — confirmed by its own test asserting the return value is `not.toBeInstanceOf(Promise)`. **This is a pure liveness check, not a readiness check** — it does NOT ping Postgres/Prisma, Redis, Qdrant (embeddings), Stripe, or any other dependency. A request reaching this handler at all proves only that the Nest HTTP layer is up and routing — it proves nothing about whether the database or any downstream service the rest of the API depends on is reachable. This is a real, source-verified finding, not an inference: there is no call to `PrismaService`, no `ConfigService` injection, nothing else in the file.
- **Response**: always `200 { status: 'ok' }` if the process is up to answer at all; there is no error path in this handler (an upstream infra failure — process crash, port not listening — is what a monitor would actually be detecting, not a response from this code).
- **No pagination/filtering/versioning** — not applicable, no input.

## Frontend usage

No reference found in `apps/mobile/src` or `apps/web/src` — confirmed by grep. This is consistent with its likely real purpose: an infrastructure-level liveness probe (load balancer / container orchestrator / uptime monitor), not an app-facing endpoint. Not claiming certainty about the specific infra consumer (no deploy/infra config was in scope to check), but no in-repo application code calls it.

## Business-rule-relevant findings for consolidation

- **BR-HEALTH-001**: `GET /health` is a liveness-only check (process responds to HTTP) with zero dependency verification. A test scenario expecting this endpoint to reflect database/Redis/Qdrant health will fail — not because of a bug, but because that is simply not what this endpoint does. If a readiness check (one that does verify dependencies) is needed for test orchestration, it does not exist yet — flag as a gap, not assume one exists elsewhere unverified.
