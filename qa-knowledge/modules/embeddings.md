# Module: Embeddings

2 endpoints, `apps/api/src/embeddings/` (`embeddings.controller.ts` — tiny, 2 routes — backed by a large subsystem: Qdrant vector DB client, OpenRouter embedding provider, BullMQ-based reconciliation/backfill processors, visual-classification services). The controller itself is the only part in scope for this batch; the worker-side processing (`listing-embedding.processor.ts`, `reconciliation.processor.ts`, `visual-classification*.service.ts`) runs in a **separate worker process** (`embeddings-worker.module.ts`, confirmed by the controller's own comment: "it never runs `ReconciliationService` itself — that lives in the worker process only") and was not read in depth — these two routes are thin triggers into that subsystem, not the subsystem itself.

Analyzed against commit `91e0447b`. Same operational shape as `seed` (dev-only, `NODE_ENV` production-gated, no other auth) — the controller's own doc comment makes this explicit: "mirrors SeedController's shape exactly (same production guard, same reasoning)."

## Both routes share one access-control pattern

**No guard decorators at all** — the only gate is `if (this.config.get('NODE_ENV') === 'production') throw new NotFoundException()`, identical in shape to `modules/seed.md`'s finding. In any non-production environment, both routes are callable by any unauthenticated caller who can reach the host. Same 404-not-403 reasoning applies (don't reveal the route exists in production).

## 1. `POST /embeddings/backfill` (`:30-38`)

- **Query**: `BackfillQueryDto` — `kind?: 'photo' | 'text'`, defaults to `'photo'` (so a pre-existing caller with no query param is unaffected by the newer `text` option being added later).
- **Purpose, per the controller's own comment**: a one-off catalogue backfill. Photo and text embeddings are **independent Qdrant points fed by independent job names** — an existing catalogue (listings created before this feature existed) needs **one backfill pass of each kind** to become searchable; running only the photo pass leaves pre-existing listings invisible to the semantic-text search tier entirely.
- **Synchronous, not queued**: `await this.embeddings.runBackfill(resolvedKind)` runs inline in the request/response cycle (contrast with `reconcile` below, which enqueues). For a catalogue of any real size this could be a long-running request — no timeout/streaming/progress-reporting mechanism was found in the controller; not independently verified how `EmbeddingsService.runBackfill` itself is structured (batch size, concurrency) since that's worker-subsystem internals out of this batch's intended depth.
- **Response**: `{ success: true, kind, ...result }` — exact shape of `result` not traced into `EmbeddingsService.runBackfill`'s return type in this pass.

## 2. `POST /embeddings/reconcile` (`:44-49`)

- **Purpose**: manually trigger the reconciliation sweep that otherwise runs on its own schedule. **Enqueues a job onto the real `embedding-reconciliation` BullMQ queue** (`'manual-trigger'` job name) rather than running the sweep inline — this is explicitly called out as "the API's only touchpoint with reconciliation." The actual reconciliation logic executes in the separate worker process.
- **Response**: `{ success: true, queued: true, jobId: job.id }` — confirms the job was accepted into the queue, **not** that reconciliation completed or even started. A test asserting this endpoint's *effects* (e.g., that stale embeddings were actually fixed) would need to poll/verify worker-side state separately — this endpoint's own response gives no completion signal.

## Frontend usage

Neither route has a mobile or web reference — confirmed by grep across both apps. Consistent with the "dev-only operational convenience" framing; these are presumably exercised via Swagger/curl/an ops script, same usage pattern inferred for `seed.service.ts`.

## Business-rule-relevant findings for consolidation

- **BR-EMBEDDINGS-001**: both endpoints share the exact same environment-only access gate as `seed` (`BR-SEED-002`) — no identity check in any non-production environment. Cross-reference during consolidation: this is now the **second** module with this identical pattern, worth a single consolidated finding/test-scenario in `gaps-and-conflicts.md` rather than two separate near-duplicate entries, if a platform-wide "dev-only endpoint access control" review is ever scoped.
- **BR-EMBEDDINGS-002**: `backfill` runs synchronously in-request; `reconcile` is fire-and-forget via a queue — a test verifying `reconcile`'s actual effect needs a different verification strategy (poll worker-side state) than one verifying `backfill`'s (the response itself should reflect the completed work, pending confirmation of `runBackfill`'s exact return shape).
