# Module: `connect` (Stripe Connect — seller payouts)

Batch 2 of the QA knowledge-base sweep (`seller-onboarding`). Analyzed read-only from branch `docs/qa-knowledge-base`. See `qa-knowledge/overview.md` for cross-cutting architecture facts (no global prefix, global `ValidationPipe`/`AllExceptionsFilter`, raw-body webhook mounts) assumed below.

## Files

- Controllers: `apps/api/src/connect/connect.controller.ts` (`/sellers/connect/*`, 4 routes), `apps/api/src/connect/connect-webhook.controller.ts` (`/payments/webhook/connect`, 1 route)
- Service: `apps/api/src/connect/connect.service.ts` (1323 lines)
- Repository: `apps/api/src/connect/connect.repository.ts`
- DTO: `apps/api/src/connect/dto/get-status-query.dto.ts`
- Queue: `apps/api/src/connect/connect-payout-retry.constants.ts` + `connect-payout-retry.processor.ts` (BullMQ, runs **in the API process**, not the worker — see processor's own doc comment, BRI-497)
- Module wiring: `apps/api/src/connect/connect.module.ts` — genuine `forwardRef` cycles with `PaymentsModule` and `OrdersModule` (both call back into `ConnectService`)
- Specs present: `connect.controller.spec.ts`, `connect.repository.spec.ts`, `connect.service.spec.ts`, `connect-payout-retry.processor.spec.ts` (unit, repo mocked); `test/connect.e2e-spec.ts` (opt-in, real RDS)

## Guards

- `ConnectController`: class-level `@UseGuards(JwtAuthGuard, RolesGuard)` + `@Roles('SELLER')` (connect.controller.ts:13-14) — **every** route under `/sellers/connect/*` requires a live, confirmed seller (RolesGuard's `'SELLER'` branch re-checks `isSeller` against the DB on every request via `UsersService.findRawById` — `apps/api/src/common/guards/roles.guard.ts:42-48` — not the JWT's stale claim).
- `ConnectWebhookController`: **no guards at all** (connect-webhook.controller.ts:16). Auth is the Stripe signature check inside `ConnectService.handleWebhook` (HMAC via `stripe-signature` header against `STRIPE_CONNECT_WEBHOOK_SECRET`), not a NestJS guard — a request with no/garbage signature gets a 400 from `constructWebhookEvent` throwing, not a 401/403.
- Body-parser ordering (`main.ts`, confirmed in `overview.md`): `/payments/webhook/connect` is one of the three raw-body routes mounted with `express.raw()` before the global `json()` parser. A test client must send the raw Stripe event bytes with a real/forged `stripe-signature` header, not a JSON-serialized body through a client that auto-sets `Content-Type: application/json`.

---

## Endpoints

### 1. `POST /sellers/connect/onboard`
- **File**: `connect.controller.ts:19-22` → `ConnectService.createAccount` (`connect.service.ts:123-155`)
- **Guards**: JwtAuthGuard + RolesGuard(`'SELLER'`)
- **Body**: none
- **Business rules**:
  - Idempotent: a caller who already has a `ConnectAccount` row gets that same row back (`stripeAccountId`), not a new account and not an error (connect.service.ts:124-128).
  - Race-safety: if two concurrent calls both miss the up-front check, the DB write's unique constraint (`P2002` on `ConnectAccount.userId`) is caught and the loser re-reads and returns the winner's row (connect.service.ts:143-151) — the Stripe-side call itself also carries an idempotency key `connect-account-create:${userId}` (`StripeService.createConnectAccount`) so a network-level retry can't create two Stripe accounts either.
  - **Side effect**: `sweepPendingOrdersForNewAccount` (connect.service.ts:170-184) — runs `transferForOrder` for every delivered/receipt-confirmed/unheld/paid order this seller has that predates their Connect account (`ConnectRepository.findSellerOrderIdsPendingPayout`, connect.repository.ts:90-103). Best-effort: a failure here is logged, not thrown, and does not fail the `onboard` call.
  - 404 if the user record itself can't be found (`NotFoundException`, should not occur for an authenticated caller).
- **Response**: `{ stripeAccountId: string }`
- **Errors**: `404 Not found` (orphaned user id — should not happen in practice), `500 Internal Server Error` ("Failed to save Connect account" — a genuine local-write failure after the Stripe account was already created; this is a real, non-idempotent-from-the-client's-view failure mode: the Stripe account now exists with no local row, so a client retry re-enters `createAccount` and (since the up-front `findByUserId` still misses) would create a SECOND Stripe account unless the first write eventually lands — worth a dedicated test for "retry after a local-write 500").
- **Side-effect scope**: writes `ConnectAccount`, may write/upsert `Payout` rows via the sweep.

### 2. `POST /sellers/connect/account-session`
- **File**: `connect.controller.ts:25-28` → `ConnectService.createAccountSession` (`connect.service.ts:196-204`)
- **Guards**: JwtAuthGuard + RolesGuard(`'SELLER'`)
- **Precondition**: caller must already have a `ConnectAccount` (i.e. must have called `onboard` first) — `404 "No Connect account for this seller — call onboard first"` otherwise.
- **Business rule**: one `AccountSession` client_secret backs BOTH the account-onboarding and payouts embedded Stripe components (`StripeService.createAccountSession` enables both). Mobile fetches a fresh one per screen mount — the secret is short-lived/single-use, not cached client-side.
- **Response**: `{ clientSecret: string }`
- **Errors**: `404` (no account yet).

### 3. `GET /sellers/connect/status`
- **File**: `connect.controller.ts:34-37` → `ConnectService.getStatus(userId, { force })` (`connect.service.ts:264-315`)
- **Guards**: JwtAuthGuard + RolesGuard(`'SELLER'`)
- **Query**: `GetStatusQueryDto` (`dto/get-status-query.dto.ts`) — `force?: boolean`, accepts `true`/`'true'`/`'1'` via a custom `@Transform` (connect.repository note: anything else, including absent, is falsy).
- **Business rules** (this is the most logic-dense GET in the module):
  1. No `ConnectAccount` row → returns an all-false/null shape with `exists: false` (connect.service.ts:279-291) — **not** a 404. A caller must branch on `exists`, not catch an error, to detect "never onboarded."
  2. `retryFailedPayouts(account.id)` runs unconditionally on every status read (connect.service.ts:298) — a `Payout` left `failed` from a transient Stripe error older than the 1-hour staleness window is retried inline as a side effect of a GET. (Note for test design: a GET endpoint has a real write side effect here — not purely idempotent/safe in the HTTP sense.)
  3. If `!account.payoutsEnabled` AND (`force` OR the row is stale — `Date.now() - updatedAt > RECONCILE_STALE_MS` = 1 hour, connect.service.ts:28,317-319) → live Stripe reconciliation (`reconcileAccount`, connect.service.ts:321-387): re-fetches account status from Stripe, updates the local row, and as a side effect:
     - if payouts just became enabled: retries held + failed payouts immediately, and schedules a delayed (10s) BullMQ follow-up retry (`scheduleDelayedFailedPayoutRetry`) for the capability-propagation race (BRI-497).
     - if the account just became `restricted` (or gained a previously-unseen past-due item): notifies the seller (in-app/push + email, BRI-797).
     - if the account just became `rejected`: notifies the seller (BRI-794).
     - On a Stripe API error during reconciliation, the stale-but-last-known local state is returned rather than failing the whole request (connect.service.ts:334-352).
  4. `force: true` exists specifically because onboarding completes Stripe verification in the SAME session (BRI-786) — the row is always "too fresh" to trip the 1-hour staleness check right after verification, so onboarding passes `force: true` for an immediate live check; Settings' payout screen omits it.
- **`accountStatus` derivation** (`deriveAccountStatus`, connect.service.ts:64-72 — single source of truth, shared by webhook and reconcile paths): `disabledReason` starting with `'rejected.'` → `'rejected'` (always wins); else `!payoutsEnabled && pastDue.length > 0` → `'restricted'`; else `payoutsEnabled ? 'verified' : 'pending'`. **Note**: this derivation never actually returns the literal `'verified'` string as a function result for a payouts-enabled account in `deriveAccountStatus` itself — re-check: `return payoutsEnabled ? 'verified' : 'pending';` — confirmed it does return `'verified'`. `restricted` is keyed on `past_due` specifically (blocking payouts RIGHT NOW), not `currently_due` (can include not-yet-due items) — a brand-new account mid-review reads `pending`, not `restricted`.
- **Response shape**: `{ exists, chargesEnabled, payoutsEnabled, detailsSubmitted, requirementsDue, accountStatus, disabledReason, pastDue, currentDeadline }` — see `ConnectAccountStatus` TS type in `apps/mobile/src/services/connectApi.ts:3-18` for the mirrored client shape (`accountStatus` client union: `'pending'|'verified'|'rejected'|'deauthorized'|'restricted'|null`; the `Prisma.ConnectAccountStatus` enum additionally has no `'deauthorized'` output from `deriveAccountStatus` itself — that value is only ever written directly by `onAccountDeauthorized`, never derived).
- **Errors**: none thrown in the normal path (the no-account case returns 200 with `exists: false`, not a 404).

### 4. `POST /sellers/connect/account-session/payout`
- **File**: `connect.controller.ts:40-43` → `ConnectService.createPayoutAccountSession` (`connect.service.ts:220-243`)
- **Guards**: JwtAuthGuard + RolesGuard(`'SELLER'`)
- **Business rule — BRI-340, phone 2FA gate**: before minting a payout-scoped `AccountSession`, requires `user.phoneVerifiedAt` to be within `PAYOUT_2FA_TTL_MS` = **5 minutes** (connect.service.ts:42,229-231) — tighter than the 30-minute `PHONE_VERIFICATION_TTL_MS` used by `sellers.apply()`, because this gates an active bank-detail change, not a one-time signup flow. Verification itself happens through the EXISTING `POST /sellers/phone-otp/request`/`verify` endpoints (same Twilio Verify account/number as onboarding) — there is no separate OTP flow for payouts.
  - **Admin override**: `user.phone2faOverrideUntil` (time-boxed escape hatch, set by `AdminService.clearSellerPhone2fa` — admin module, out of this batch's scope but a real dependency for a seller who lost phone access) bypasses the gate if still in the future.
  - Fails with `403 Forbidden`, body `{ code: 'PAYOUT_2FA_NOT_VERIFIED', message: 'Please verify your phone number before changing your payout account.' }` (connect.service.ts:46-48,234-237) — a structured error code, same convention as `PhoneOtpErrorCode` in sellers.service.ts, meant for client-side branching.
  - 404 if no `ConnectAccount` exists yet (same "call onboard first" message as `account-session`).
- **Response**: `{ clientSecret: string }`
- **Known related bug (open)**: `BRI-812`/done — "Opening Payout History automatically creates a Stripe Connect account — seller never started payout setup" (fixed; Linear status `Done`). Worth a regression test: opening the payout-history screen for a seller with NO Connect account must NOT silently trigger `onboard`.

### 5. `POST /payments/webhook/connect`
- **File**: `connect-webhook.controller.ts:16-33` → `ConnectService.handleWebhook(payload, signature)` (`connect.service.ts:563-619`)
- **Guards**: none (public route, raw body, Stripe-signature-verified)
- **Registered in Stripe as a `connect: true` endpoint** ("events from connected accounts") — deliberately only dispatches connected-account-scoped event types:
  - `account.updated` → `onAccountUpdated` (connect.service.ts:621-683): updates `chargesEnabled`/`payoutsEnabled`/`detailsSubmitted`/`requirementsDue`/`pastDue`/`currentDeadline`/`accountStatus`; on a new rejection/restriction, notifies the seller (same best-effort in-app+email channels as the reconcile path); on a payouts-enabled transition, retries held + failed payouts and schedules the delayed BullMQ follow-up.
  - `account.application.deauthorized` → `onAccountDeauthorized` (connect.service.ts:843-863): seller revoked Redspur's Stripe access from their own side. Sets `chargesEnabled: false, payoutsEnabled: false, accountStatus: 'deauthorized'` and alerts EVERY admin (`notifyAdmins`, in-app only — no email channel for this one).
  - **Deliberately NOT dispatched here** (connect.service.ts:599-608): `charge.dispute.*` and `transfer.*`. Under Separate Charges & Transfers both the Charge and Transfer objects live on the PLATFORM account, so Stripe never actually delivers them to a `connect: true` endpoint in production — they arrive instead via `StripeService.handleWebhook` (`/payments/webhook`, payments module, `connect: false`), which calls `ConnectService.onChargeDisputeCreated`/`onChargeDisputeClosed`/`onTransferCreated`/`onTransferReversed`/`onChargeDisputeFundsWithdrawn`/`onChargeDisputeFundsReinstated` — same business logic, different entry controller. **A test driving these five event types through `POST /payments/webhook/connect` is testing the wrong route** — they belong to the `payments`/`payment-methods` batch's webhook, not this one, even though the handler methods live in `ConnectService`.
- **Idempotency**: `WebhookEvent` row per `stripeEventId` (`WebhookEventsRepository.findOrCreate`/`markProcessed`/`markFailed`) — an event already `processed` is skipped outright (200, no-op); one still `failed`/new is (re)attempted. A handler that throws re-throws out of `handleWebhook` so Stripe's own retry mechanism redelivers (NOT swallowed into a 200).
- **Signature verification**: `STRIPE_CONNECT_WEBHOOK_SECRET` (separate secret from the platform `/payments/webhook`, since Stripe issues one signing secret per registered endpoint) — invalid signature throws `BadRequestException` ("Invalid Stripe webhook signature"), a clean 400, before the event is even parsed into a type.
- **Response**: `{ received: true }` on success (`HttpCode(200)` explicitly, not the Nest POST default 201).
- **Errors**: `400` (bad signature); otherwise the original handler error rethrown → `AllExceptionsFilter` shapes it to a 5xx, and Stripe will retry the delivery on anything other than a 2xx.

---

## Shared business logic reachable only indirectly (not its own route, but load-bearing for test setup / assertions)

These are `ConnectService` methods with no direct controller route — they're triggered by other modules' actions (checkout, receipt confirm, refund) and by the webhook/reconcile paths above. A test scenario that wants to observe a `Payout` transition needs to drive these indirectly (see `fragments/seller-onboarding.dependency-map.json`).

- **`transferForOrder(orderId)`** (connect.service.ts:487-546) — the actual payout-creation logic. Gates, in order: `payoutHeld` must be false; `sellerAmount > 0`; `payment.stripeChargeId` must exist; if `STRIPE_CONNECT_TRANSFER_TIMING` (env, default `'after_report_window'`) is the default, `deliveredAt` must be set AND at least 3 days (`TRANSFER_HOLD_WINDOW_MS`) must have passed; a `Payout` already `transferred` is a no-op; no `ConnectAccount` at all → no-op (nothing written, picked up later by `sweepPendingOrdersForNewAccount`); not `payoutsEnabled` → writes `Payout.status = 'held_unverified'`; otherwise calls Stripe and writes `'transferred'` or `'failed'`.
- **`refundOrder(orderId, amount?)`** (connect.service.ts:1208-1245) — refund entry point for cancellations/disputes; blocks with `400` if there's an open (unresolved) `StripeDispute` on the order; reverses any already-transferred payout first (`reverseTransferIfNeeded`, called TWICE — once up front, once again immediately before the Stripe refund call, closing a race window per BRI-497 follow-up); a reversal failure records `Payout.status = 'reversal_failed'`, alerts every admin, and blocks the refund entirely (`400`, "our team has been notified") rather than refunding the buyer while leaving the seller's transfer un-reversed.
- **`onChargeDisputeCreated`/`onChargeDisputeClosed`/`onChargeDisputeFundsWithdrawn`/`onChargeDisputeFundsReinstated`/`onTransferCreated`/`onTransferReversed`** — public methods, dispatched from `StripeService.handleWebhook` (`/payments/webhook`, a different module/batch), not from this module's own webhook controller. Documented here because the business logic and the `Payout`/`StripeDispute` schema both live in this module.
- **`runQueuedFailedPayoutRetry(connectAccountId)`** — entry point for `ConnectPayoutRetryProcessor` (BullMQ job, 5 attempts, exponential backoff starting at 10s — `connect.module.ts:38-39`), not reachable from any HTTP route.

---

## Prisma models touched

- `ConnectAccount` (schema.prisma:963-997) — `userId` unique, `stripeAccountId` unique, `chargesEnabled`/`payoutsEnabled`/`detailsSubmitted` booleans, `requirementsDue`/`pastDue` JSON string arrays, `currentDeadline` DateTime, `accountStatus` enum (`pending|verified|rejected|deauthorized|restricted`, default `pending`).
- `Payout` (schema.prisma:1273-1295) — `orderId` unique (one payout per order), `connectAccountId`, `amount` (int cents), `reversedAmount` (cumulative, default 0 — a partial reversal does NOT flip `status` to `'reversed'` until the running total reaches `amount`, BRI-497), `status` enum `PayoutStatus` (confirmed in schema.prisma:114-125: `pending|held_unverified|transferred|reversed|failed|reversal_failed`), `heldReason`, `stripeTransferId` unique.
- `StripeDispute` (schema.prisma:1385-1424) — a real Stripe-side chargeback, **distinct from** the internal `Dispute` model owned by the `disputes` module — do not confuse the two in test fixtures. `stripeDisputeId`/`stripeChargeId`, `status` (raw Stripe string, e.g. `needs_response|won|lost|warning_closed`), `evidenceDueBy`, `writtenOffAt`/`writtenOffById` (admin-only audit stamp), `fundsWithdrawnAt`/`fundsReinstatedAt`.
- `WebhookEvent` (schema.prisma, shared with `/payments/webhook`) — dedup table, `stripeEventId` unique.
- `User.phoneVerifiedNumber`/`phoneVerifiedAt`/`phone2faOverrideUntil` — read by the payout 2FA gate; written by `POST /sellers/phone-otp/verify` (sellers module) and by `AdminService.clearSellerPhone2fa` (admin module) respectively.

## External dependencies

- **Stripe Connect** (`StripeService` in `apps/api/src/payments/payments.service.ts`) — `createConnectAccount`, `createAccountSession`, `createPayoutAccountSession`, `retrieveAccountStatus`, `createTransfer`, `createTransferReversal`, `refundOrderPayment`, `constructWebhookEvent`, `reverseTaxTransactionForChargeback`/`reinstateTaxAfterChargebackReversed`. Not re-traced in full here (owned by the `payments` batch) — treat as an opaque boundary; every call site above either has an idempotency key or a documented best-effort/fail-open posture.
- **BullMQ/Redis** — `connect-payout-retry` queue, 5 attempts, exponential backoff (10s base), `removeOnComplete: 100`/`removeOnFail: 500`.
- **Notifications/Mail** — `NotificationsService.create` (in-app/push) and `MailService.sendPayoutActionRequired`/`sendPayoutAccountRejected` (connect.service.ts:760-832) for restricted/rejected account state changes; both best-effort (failure logged, never thrown back to the webhook/reconcile caller).

## Known open issues from Linear (cross-checked against code)

| Ticket | Team | Status | Relevance |
|---|---|---|---|
| REDB1-44 (copy of BRI-832) | REDB1 | **Reopened** | "Bank step loops back to 'Select an account for payouts' after successful Stripe connection — linked account not shown, Continue disabled." The onboarding step does not pick up a just-linked bank account from the embedded Stripe flow; workaround is Seller Hub → Payout Details → Finish Setup. Directly touches `GET /sellers/connect/status`'s reconcile timing/`force` behavior and the embedded AccountSession component, not a pure backend bug per the ticket's own notes (dev confirms "bank account is linked on the Stripe side, but the onboarding step does not pick it up") — likely a mobile polling/refresh gap after the embedded component reports success, worth a scenario that asserts `GET /sellers/connect/status?force=true` reflects a just-linked external account promptly. |
| REDB1-48 (copy of BRI-786) | REDB1 | **Reopened** | "First-time seller cannot continue after Stripe verification — shop is activated only after re-verifying from Settings → Payment details." This is the exact scenario `getStatus`'s `force` flag (connect.service.ts:255-263) was built to fix (BRI-786, previously closed) — now reopened, meaning the fix regressed or is incomplete. High-value regression test: complete Stripe verification inside onboarding, confirm the onboarding flow itself (not a later Settings re-visit) sees `payoutsEnabled: true`/the shop activate without a second verification. |
| REDB1-131 (copy of BRI-840) | REDB1 | Todo | "Payout details screen does not load for a seller with incomplete Stripe onboarding — shows generic Stripe error." Per dev note, happens only when payout setup was started but not finished. Backend-visible angle: confirm `GET /sellers/connect/status` for an account that exists with `detailsSubmitted: false` returns a well-formed, non-error 200 (it should, per the code read above) — if the web/mobile screen is instead crashing on `createAccountSession`/`createPayoutAccountSession` for an incomplete account, that's the real suspect endpoint to probe. |
| REDB1-139 (copy of BRI-826) | REDB1 | Todo | "Bank account card shows 'Not connected' when a bank account is linked in Stripe" (restricted-but-linked account). Frontend mis-maps `accountStatus`/`pastDue` into a binary connected/not-connected UI rather than reflecting the real three-way state (linked-and-restricted vs never-linked). Good source for `TS-CONNECT` scenarios asserting the distinct `pastDue`/`accountStatus: 'restricted'` fields are both present and non-conflicting in the API response. |
| BRI-812 | BRI | Done | "Opening Payout History automatically creates a Stripe Connect account — seller never started payout setup." Fixed; good regression-test candidate (see endpoint 4 above). |
| BRI-497 | BRI | Done | "[Payouts] Balance stays $0.00 after Stripe verification for an order completed while unverified" — this is the `held_unverified`/`retryHeldPayouts`/`sweepPendingOrdersForNewAccount` machinery documented above, confirmed fixed and extensively commented in code. |
| REDB1-146 (copy of BRI-810) | REDB1 | Todo (acceptance criteria still draft) | "Enforce under-18 block on financial agreements using dateOfBirth" — **not implemented**. No age check exists anywhere in `ApplySellerDto`/`SellersService.apply`/`ConnectService` today (confirmed by reading both — neither references `dateOfBirth`). A compliance gap, not a drift bug: a known-missing control, not a known-broken one. |

No Linear ticket found (searched "commission", "shop name", "connect", "payout", "onboarding", "stripe") that describes `BRI-497`'s capability-propagation race fix in more detail than the code comments already give — the code comments are the more complete source for that one.
