# Module: payments

**Endpoint**: `POST /payments/webhook` — `apps/api/src/payments/payments.controller.ts:17-25`

**Not in this module's scope but adjacent** (do not re-derive, cross-reference only): `POST /payments/webhook/connect` is a sibling raw-body route (`main.ts:25`) owned by `ConnectModule`, handling connected-account-scoped Stripe events. It shares `WebhookEventsRepository`'s dedup table (`webhook-events.repository.ts`'s own doc comment names both routes explicitly) but has its own controller/service outside this module. Stripe Connect account lifecycle, transfers, payouts are `connect.module.ts`'s territory.

---

## Controller → Service → Repository trace

- **Controller**: `PaymentsController` (`payments.controller.ts`), `@Controller('payments')`, no class- or method-level guard — correct, because Stripe cannot present a JWT. `@Post('webhook')`, `@HttpCode(HttpStatus.OK)` (always 200 on success, per Stripe's expectation). No DTO: the body is the raw `Buffer` written by `main.ts`'s `express.raw({ type: 'application/json' })` mount (registered *before* the global `json()` parser — see `main.ts:20`), read via `@Req() req: Request` and cast `req.body as Buffer`. The only other input is the `stripe-signature` header via `@Headers('stripe-signature')`.
- **Service**: `StripeService.handleWebhook(payload: Buffer, signature: string)` in `payments.service.ts:727-824`.
- **Repositories**: `PaymentsRepository` (Order/Payment reads+writes), `WebhookEventsRepository` (dedup ledger).
- **Guards actually applied**: none. Security for this route is entirely the Stripe signature check inside the service, not a Nest guard.
- **AllExceptionsFilter interaction**: an invalid/unverifiable signature throws `BadRequestException` (→ 400, Stripe stops retrying — correct, since retrying a bad signature can never succeed). Any other thrown error inside an event handler is caught by `handleWebhook`'s own try/catch, which marks the event `failed` in `WebhookEvent` and **rethrows** — this reaches `AllExceptionsFilter` and produces a 500, which Stripe's retry schedule picks up. This rethrow-to-retry pattern is deliberate (see `onPaymentSucceeded`'s doc comment) and is the mechanism that makes several races "self-heal."

## Signature verification (`handleWebhook`, `payments.service.ts:727-736`)

- Secret: `STRIPE_WEBHOOK_SECRET` via `config.getOrThrow` (boot-fails if unset — not a runtime 500).
- Verification: `this.client.webhooks.constructEvent(payload, signature, secret)` — the official Stripe SDK verifier, which both checks the HMAC and parses the JSON. A tampered or wrongly-signed body throws inside the SDK; caught and logged at `warn`, rethrown as `BadRequestException('Invalid Stripe webhook signature')`.
- **Hard dependency on raw bytes**: this only works because `main.ts` mounts `express.raw({ type: 'application/json' })` on `/payments/webhook` ahead of `json()`. A test client that JSON-serializes and lets a normal HTTP client set `Content-Type: application/json` the usual way will still work *as long as it sends the exact byte sequence Stripe signed* — the common failure mode is re-serializing the parsed JSON (changes whitespace/key order) before computing/sending the signature, which invalidates it.

## Idempotency / replay handling (`WebhookEventsRepository`, `webhook-events.repository.ts`)

- **True dedup, not just "retry-safe handlers"**: `findOrCreate` is a Postgres `upsert` keyed on `stripeEventId` (atomic — no read-then-write race between two concurrent deliveries of the same event). If the row's `processingStatus` is already `'processed'`, `handleWebhook` logs and returns immediately — the event's business logic does **not** re-run.
- A row in `'failed'` or fresh `'received'` status is **not** skipped — it is processed (or re-processed) normally. This is the Stripe-retry path: a delivery that failed (handler threw) is expected to come back and this is intentionally not treated as already-done.
- Net effect: Stripe's own automatic retries (it retries a non-2xx webhook response on a backoff schedule) are safe — a 500 followed by a later successful retry runs the handler exactly once to completion; a 200 followed by an accidental re-delivery (Stripe does occasionally double-deliver) is a clean no-op.

## Event-type dispatch (`handleWebhook`, `payments.service.ts:753-814`)

| Event | Handler | Effect |
|---|---|---|
| `payment_intent.succeeded` | `onPaymentSucceeded` | Upserts `Payment` row to `succeeded`; files Stripe Tax transaction if not already filed; marks listings `sold` + realtime broadcast + embedding sync; notifies seller ("You made a sale!"); closes competing offers on the same listings (`OffersService.cancelCompetingOffers`) — **only** on first-time success (guarded by `alreadySucceeded`, computed from the Payment row's state *before* the upsert). |
| `payment_intent.payment_failed` | `onPaymentFailed` | Order → `cancelled`; `Payment` → `failed`; notifies buyer. No-op (warn, no throw) if no matching Order — this is the **expected, permanent** case for a failed offer-hold authorization attempt that never had an Order. |
| `payment_intent.canceled` | `onPaymentCanceled` | Order → `cancelled`; `Payment` → `canceled`. No-op if no matching Order — same reasoning as above: every declined/expired/superseded offer cancels its hold PaymentIntent and produces this event with no Order to match, constantly, by design. |
| `charge.refunded` | `onChargeRefunded` | Resolves Order via `payment_intent`; no-op if `Payment` already `refunded`; computes full-vs-partial from `Charge.amount_refunded` (cumulative, not incremental) vs. `Payment.amount`; reverses the filed Stripe Tax transaction by the **increment** (current cumulative minus previously-recorded cumulative) — a safety net for a Dashboard-initiated refund, since `refundOrderPayment` (the app-initiated path) already does its own reversal and this handler is a no-op against its own refund (status already updated). |
| `charge.dispute.created` / `.closed` / `.funds_withdrawn` / `.funds_reinstated` | dispatched via `dispatchToConnect` | Forwarded into `ConnectService` (platform-account dispute/chargeback handling) — **cross-reference `connect`/orders-disputes agent's output, not re-derived here**. A missing `ConnectService` wiring (should never happen in practice — `@Optional()` purely for a defensive DI shape) logs at `error`, not silent. |
| `transfer.created` / `transfer.reversed` | dispatched via `dispatchToConnect` | Same forwarding, Connect-side payout/transfer bookkeeping — cross-reference only. |
| anything else | — | Silently ignored (falls through every `else if`), still marked `processed`. |

Every branch runs inside the outer try/catch described above — a thrown error from any handler marks the whole delivery `failed` and rethrows for Stripe to retry the entire event (not just the failed sub-step).

### Amount-mismatch handling
`onPaymentSucceeded` compares the webhook's `amount` to `Order.total`; a mismatch is logged at `error` but **does not block** recording the payment as succeeded — "Stripe already charged the card by the time this event lands... can't refuse a successful charge." A test that deliberately desyncs `Order.total` from the PaymentIntent amount (e.g. racing a price change) should assert the log, not a rejected webhook.

### Tax filing/reversal side effects (cross-cutting, owned here)
- `onPaymentSucceeded` files a Stripe Tax Transaction from `Order.taxCalculationId` once, guarded only by `!order.taxTransactionId` (a prior version also gated on `!alreadySucceeded`, which was a real production bug: it silently skipped tax filing for every accepted-offer order, since those always hit this webhook with `Payment` already `succeeded` synchronously from `acceptOffer`). `fileTaxTransaction` re-checks the Payment's **current** status right before filing, closing a cancellation race the outer snapshot wouldn't catch.
- `onChargeRefunded`/`refundOrderPayment`/`reverseTaxTransactionForChargeback`/`reinstateTaxAfterChargebackReversed` all reverse/re-file tax transactions idempotently, each keyed by a value guaranteed unique per **event** (not per cents amount — a documented code-review finding: two refunds of the identical amount on the same order would otherwise collide on Stripe's idempotency layer and the second would silently never happen).

## Business flow boundary

`StripeService.confirmOrderPayment` (a **synchronous** poll, called directly by `OrdersService.create` right after `createPaymentIntent` confirms) and this **asynchronous** webhook both write to the same `Payment` row via `upsertPayment` — this is intentional double coverage for the case where the buyer's client never calls back (e.g. app killed after a 3DS redirect). The order-status state machine itself (`placed → paid → shipped → delivered`, cancellation/dispute transitions) is owned by `orders`/`disputes` — cross-reference the orders-disputes agent's output; this document only covers what the payments webhook writes, not the full state machine.

## Tests

`payments.controller.spec.ts` — thin: asserts the controller forwards `(rawBody, signature)` to `StripeService.handleWebhook` and that a handler rejection propagates (not swallowed). `payments.service.spec.ts` (86KB) is the real coverage — every event branch, idempotency, amount-mismatch, tax filing/reversal paths. Mocks the repository/Stripe client, not Prisma directly, per `apps/api/CLAUDE.md`'s testing convention.
