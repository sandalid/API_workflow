# Module: shipping

**Endpoints** (both under `@Controller('shipping')`, split across two controller files in the same `ShippingModule`):

- `GET /shipping/tiers` — `shipping.controller.ts:12-23` (public, no guard)
- `POST /shipping/webhook/shippo` — `shippo-webhook.controller.ts:19-28` (public by necessity — raw body, no JWT possible)

Also traced for data-dependency purposes (not separately-scoped endpoints): `shipments.repository.ts`, `shippo.service.ts`'s `getTrackingMode()`, `shippo-status.mapping.ts`, `best-fit-package.util.ts` — all consumed indirectly by the two endpoints above or by other modules (`orders`, `disputes`, `sellers`) that purchase/poll shipments, which this analysis does not re-derive.

---

## `GET /shipping/tiers`

### Controller → Service → trace
No service layer at all — `ShippingController.getTiers()` (`shipping.controller.ts`) reads directly from the in-memory constant `SHIPPING_TIERS` (`shipping.constants.ts`) and maps it to `ShippingTierDto[]`. No repository, no Prisma, no DB round-trip. **Guard**: none — deliberately public (code comment: "both the web/mobile Shipping Fees pages and the mobile listing-details tier picker need it before a seller is necessarily authenticated as a seller", BRI-460).

### Is it static config or DB-driven?
**Entirely static, code-configured.** `SHIPPING_TIERS` is a hard-coded `readonly` array of 4 tiers. A `ShippingConfigService`/`ShippingConfigRepository`/`ShippingConfig` table existed at one point and was **deliberately removed** (2026-09-17, per `shipping.module.ts`'s comment: "Buy Now and offers both use a fixed, non-admin-configurable $10... any configurability is an explicit separate CR"). There is no admin UI, no env var, no seed-dependent row behind this endpoint — a test against it needs **zero** test-data setup; it will return the same 4 tiers from a fresh checkout of the repo.

### The 4 tiers (`shipping.constants.ts:60-93`)
| key | name | priceCents | maxWeightLb | estimatedDays |
|---|---|---|---|---|
| SMALL | Small Package | 499 | 1 | 3–5 business days |
| MEDIUM | Medium Package | 899 | 5 | 3–5 business days |
| LARGE | Large Package | 1499 | 20 | 5–7 business days |
| EXPEDITED | Expedited | 1999 | null (speed choice, not a weight band) | 1–2 business days |

`findShippingTier(key)` (same file) is the lookup other modules use to validate a listing's chosen tier key server-side — not itself exposed as an endpoint.

### Single-source-of-truth note
These literals are also the source for `ai/shippability.ts`'s `suggestShippingTierFromWeight` (re-exported `MAX_WEIGHT_LB`/`MAX_LENGTH_PLUS_GIRTH_IN` constants) and are consumed by three independent frontends — mobile's Seller Hub "Shipping Fees" page, mobile's listing-details tier picker, and web's `apps/web/src/app/seller/shipping/page.tsx` (via `sellerApi.getShippingTiers()`, `apps/web/src/lib/sellerApi.ts:624-626`). None of the three may re-declare the numbers independently — a test asserting tier content should assert against this one file, not a hard-coded expectation duplicated per frontend.

### Frontend usage
- **Mobile**: `apps/mobile/src/services/shippingApi.ts` — `shippingApi.getTiers()` calls `GET /shipping/tiers`, caches the last successful response in a module-level variable, and **serves the stale cache on a fetch failure** rather than erroring (same "last-good-answer" discipline as `categoriesApi.ts`). A test scenario should cover: first call populates the cache; a subsequent failed call returns the cached list, not an error; a failed call with no prior cache still throws (wrapped as a real `Error`, not the raw `ApiError` object literal apiClient throws).
- **Web**: `apps/web/src/lib/sellerApi.ts:624-626` → `GET /shipping/tiers`, consumed by `apps/web/src/app/seller/shipping/page.tsx` (the Seller Shipping Fees admin/seller page). No other web usage found — admin does not otherwise touch the shipping module directly; it only sees results (shipment status) via the orders/admin surfaces, out of this module's scope.

---

## `POST /shipping/webhook/shippo`

### Controller → Service → trace
- **Controller**: `ShippoWebhookController` (`shippo-webhook.controller.ts`), no guard — correct, Shippo cannot present a JWT. Inputs: raw `Buffer` body (same `main.ts` raw-body mount as `/payments/webhook`, registered at `main.ts:30`), `?token=` query string, and the `shippo-auth-signature` header.
- **Service**: `ShippoWebhookService.handleTrackingWebhook` (`shippo-webhook.service.ts:80-134`).
- **Repository**: `ShipmentsRepository.findByCarrierAndTrackingNumber`.
- **No DTO**: raw bytes, parsed manually (`JSON.parse` inside `parsePayload`, with a `BadRequestException` on malformed JSON).

### Tracking-mode gate — the first thing a test must account for
`main.ts`'s comment says this route is "mounted unconditionally (not just when `SHIPPO_WEBHOOK_HMAC_SECRET` is set) so enabling HMAC later is a config-only change" — **confirmed true for the raw-body mount**, but the *handler itself* has its own, separate gate: `handleTrackingWebhook`'s very first check is `this.shippo.getTrackingMode() !== 'webhook'`, and if tracking mode is anything else (including unset — `polling` is "the documented production mode"), the entire request is a **no-op**: logged at `warn`, returns `undefined`, controller still answers `{ received: true }` with a 200. **No signature verification happens at all in this mode** — not because auth is skipped, but because the whole handler short-circuits before reaching `verifyAuthenticity`. A test suite must set up both modes to exercise different things:
  - `SHIPPO_TRACKING_MODE` unset/`polling` → assert the no-op (200, no DB write, no event emitted), regardless of what signature/token is sent.
  - `SHIPPO_TRACKING_MODE=webhook` → the full signature-verification + processing path below actually runs.

### HMAC/auth verification (only reached in `webhook` mode) — `verifyAuthenticity`/`verifyHmac`
- **Precedence**: HMAC (`SHIPPO_WEBHOOK_HMAC_SECRET`) wins over the URL token (`SHIPPO_WEBHOOK_URL_TOKEN`) if both are configured.
- **HMAC scheme** (documented, **never live-verified against a real Shippo delivery** — the BRI-257 POC never received one): header `shippo-auth-signature: t=<unix_ts>,v1=<hex_hmac_sha256>`; signed string is `"<timestamp>.<rawBody>"`; `createHmac('sha256', secret)`; compared with `timingSafeEqual` (constant-time, avoids a timing side-channel). Missing header → `401`; malformed header (`t=`/`v1=` not both present) → `401`; mismatch → `401`.
- **URL-token fallback**: `?token=` compared constant-time against `SHIPPO_WEBHOOK_URL_TOKEN`; missing/mismatched → `401`.
- **Fail-open if neither secret is configured**: logs a `warn` ("DEV-only posture") and **accepts the request unauthenticated**. In practice this path can only be reached by a local dev boot that bypasses env validation — `env.validation.ts`'s `validate()` **fails boot** if `SHIPPO_TRACKING_MODE=webhook` is set with neither secret configured (`env.validation.ts:38-41`). A test exercising "neither secret configured" therefore has to construct the service directly (bypassing the module's own boot-time guard) rather than via a normally-booted app.

### Payload parsing and routing
- Non-`track_updated` events are logged at `debug` and ignored (2xx, no further processing) — Shippo's webhook can in principle deliver other event types; this endpoint only cares about tracking.
- Missing `carrier`/`tracking_number`/`tracking_status.status` → `BadRequestException` (400 — Shippo should NOT retry a payload shape it sent broken).
- Field names are read **defensively in both snake_case and camelCase** (`tracking_number` ?? `trackingNumber`, etc.) because the exact wire shape was sourced from Shippo's docs, never confirmed against a live delivery.
- **Shipment resolution**: `ShipmentsRepository.findByCarrierAndTrackingNumber(carrier, trackingNumber)` — case-insensitive carrier match, no DB uniqueness on the (carrier, trackingNumber) pair (a shared staging test tracking number reused across orders is a real, intentional case). More than one match is resolved to the most-recently-created row and logged at `error` for manual investigation — not a 500, not silently picking one with no trace.
- **No matching Shipment** → `warn`-logged no-op, 200 — "a webhook for a tracking number Redspur never purchased... is expected occasionally, and Shippo must not be given a reason to retry it."

### What happens on a successful match
Emits `SHIPPO_TRACKING_UPDATED_EVENT` (`'shippo.tracking-updated'`) via `EventEmitter2.emitAsync` — **awaited**, so an unhandled error in whatever listens (per the module header comment: `OrdersService`/`DisputesService`, each filtering by `shipment.kind` via their own `@OnEvent` handlers) propagates back through this call, reaches `AllExceptionsFilter`, and produces a 500 that Shippo retries. This module deliberately has **zero direct dependency** on `OrdersModule`/`DisputesModule` — a prior version injected them directly and that forced a `forwardRef` cycle cascading into `AddressesModule` too (documented in the module's own comment, with a pointer to git history). **The actual order/dispute status transition logic this event triggers is out of this module's scope** — cross-reference the orders-disputes agent's output for `OrdersService.applyOutboundTrackingStatus`/`DisputesService.applyReturnTrackingStatus`.

### Error-vs-retry contract, summarized
| Condition | Response | Shippo retries? |
|---|---|---|
| Tracking mode not `webhook` | 200 (no-op) | No (correctly — nothing to retry) |
| Bad/missing signature or token (webhook mode) | 401 | No (per Shippo's own docs: no retry on non-timeout/429/5xx 4xx) |
| Malformed JSON / missing required fields | 400 | No |
| Non-`track_updated` event | 200 (no-op) | No |
| Unknown carrier+tracking pair | 200 (no-op) | No |
| Listener (`Orders`/`Disputes`) throws | 500 (propagated) | Yes |

### Dependency: does a test need a real Shippo-side shipment?
To exercise the "successful match" path, the test only needs a **local** `Shipment` row with a matching `(carrier, trackingNumber)` — nothing calls out to Shippo's API from this webhook path itself (`ShippoService` is injected only for `getTrackingMode()`, a config read). A genuinely end-to-end test (purchase a real label in Shippo's sandbox, then have Shippo deliver a real webhook) is a different, much heavier dependency this analysis cannot size further (the shippo MCP integration needed to inspect Shippo's own sandbox/test-webhook tooling failed to connect this session — see blockers in `payments-shipping.gaps.md`).

## Cross-reference / boundary gap (flagged, not owned here)
`Shipment.labelUrl`/`Shipment.qrCodeUrl` — populated by the label-purchase flow (owned by `sellers`/`orders`, not this module) — store long-lived (~1 year), **unauthenticated bearer links** to Shippo-hosted PDFs/PNGs containing shipping PII (BRI-848, status: Todo, MobSF dynamic security finding). The endpoint that *returns* these to a seller (`POST /sellers/me/orders/{orderId}/shipping-label`) is outside this module's 6-endpoint scope, but the data these links point at lives in this module's `Shipment` model and is read back by this module's tracking webhook/polling path — noted here because a payments/shipping-focused security review would otherwise miss it by searching only this module's own controllers.

## Tests
`shipping.controller.spec.ts` — static-content assertions (exact 4 tiers, exact prices). `shippo-webhook.controller.spec.ts` — thin, forwards-correctly + propagates-failure shape, same pattern as `payments.controller.spec.ts`. `shippo-webhook.service.spec.ts` (~10KB) — the real coverage: tracking-mode gate, both auth schemes, malformed payload, ambiguous-match logging, event emission. `shipments.repository.spec.ts` covers the claim/release/upsert/ambiguous-lookup repository logic directly.
