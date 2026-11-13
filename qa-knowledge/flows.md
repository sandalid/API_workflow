# End-to-End Flows

Every flow below is assembled from the endpoint-level evidence already recorded in `modules/*.md` and `business-rules.json` — step citations point back to those files rather than re-deriving file:line evidence here. A step marked **[inferred]** is a reasonable sequencing conclusion from combining several endpoints' own documented preconditions/effects, not something one single piece of code states as an explicit pipeline; everything else is directly confirmed by reading the relevant service method.

---

## Flow 1 — Buyer account creation and sign-in (OTP-based, the real production path)

**Entry point**: mobile `EmailEntry` screen.

1. Buyer types an email → `authApi.checkAvailability` → `GET /auth/check-availability` (UX pre-check only, not the security boundary).
2. `authApi.requestOtp` → `POST /auth/otp/request`. Server checks an email-scoped lockout first (`BR-AUTH-007`), mints a bcrypt-hashed 6-digit code with a 1-minute TTL restamped to send time (`BR-AUTH-009`), emails it.
3. Buyer enters the code (+ an onboarding-draft payload if this is a new account: name, username, prefs, sizes, zip, ageBracket, gender) → `authApi.verifyOtpLogin` → `POST /auth/otp/verify`.
   - **New email** → account created on the spot (`isNewUser: true`), username honored or auto-derived (`BR-AUTH-011`), onboarding-draft fields persisted **only on create**.
   - **Existing email, correct code** → `cancelPendingDeletionOnLogin()` runs (`BR-AUTH-005`) — if the account was mid-deletion-window, signing in restores it.
   - **Existing email, suspended** → 401, flow ends.
4. Response includes a rolling-refresh-token session (`token`/`refreshToken`, 45-min access / 90-day rotating refresh, `BR-AUTH-028`) and the full `user` object (incl. `sellerStatus`, onboarding facets).
5. Mobile persists the refresh token in SecureStore; `GET /users/me` is the identity-bootstrap call on every cold start thereafter.

**Alternative entry points, same session-issuing tail**: `POST /auth/social/google`/`apple`/`facebook` (provider-token verified, same account-create-or-restore logic minus the onboarding draft — `BR-AUTH-012`/`013`). **Known gap**: Apple/Facebook sign-in does **not** run `cancelPendingDeletionOnLogin` (`BR-AUTH-014`) — a deleted-then-returning user via those two providers stays scheduled for deletion.

**Session maintenance, background**: `apiClient`'s 401-interceptor silently calls `POST /auth/refresh` with the stored refresh token to mint a fresh access token + a rotated refresh token (`BR-AUTH-020`); a replayed-already-revoked token revokes the whole rotation family (`BR-AUTH-019`).

---

## Flow 2 — Seller onboarding, phone verification, Stripe Connect activation

**Entry point**: mobile Sell-tab / Settings "Become a seller."

1. `POST /sellers/phone-otp/request` → Twilio Verify SMS (real in prod; a hardcoded test number bypasses Twilio in non-prod, `BR-SELLERS-003`).
2. `POST /sellers/phone-otp/verify` → stamps `User.phoneVerifiedNumber`/`phoneVerifiedAt` — the trust anchor the next two steps both read back, with **different TTLs for different purposes** (30 min for `apply()`, 5 min for the payout-2FA gate, `BR-CONNECT-008`).
3. `POST /sellers/apply` — full seller-profile submission (sellerType/taxId/shopName/address/phone). Server re-checks phone-verification freshness, shop-name availability (this time correctly `excludeUserId`-scoped, unlike the live-typing check endpoint — `BR-SELLERS-002`), and ship-from address deliverability via Shippo (fails open on a Shippo outage, hard-blocks on an explicit "undeliverable" verdict — `BR-SELLERS-004`). **`isSeller: true` is set immediately** — no email-confirmation step, no Stripe Connect requirement yet (`BR-SELLERS-005`).
4. Separately, for payout capability: `POST /sellers/connect/onboard` (idempotent — `BR-CONNECT-001`) creates a Stripe Connect account; `POST /sellers/connect/account-session` mints the embedded-component client secret the mobile Connect-onboarding UI uses.
5. Once Stripe verification completes inside that embedded flow, `GET /sellers/connect/status?force=true` (the `force` flag exists specifically so this read doesn't have to wait out the normal 1-hour staleness window — `BR-CONNECT-006`) triggers a live reconciliation, flipping `payoutsEnabled: true` and the derived `accountStatus` to `'verified'` (`BR-CONNECT-007`).
6. Any order that reached a payable state **before** step 4 completed is swept automatically (`sweepPendingOrdersForNewAccount`, `BR-CONNECT-002`) — the seller doesn't have to do anything to collect a payout for a sale that happened during the gap.

**Known regression in this exact flow**: `REDB1-48`/`BRI-786` is Reopened — the scenario step 5's `force` flag was built to fix (seller stuck needing a second Settings visit after onboarding verification) is back (see `gaps-and-conflicts.md` § 3).

**Payout-detail changes, a separate narrower gate**: `POST /sellers/connect/account-session/payout` requires phone verification within the last **5 minutes** specifically (not 30), with an admin-settable time-boxed override (`clearSellerPhone2fa`, `BR-CONNECT-008`).

---

## Flow 3 — Listing creation → review → go-live

1. Seller photographs items → `POST /ai/analyze` (seller-role-gated, rate-limited) returns a suggested title/category/condition/price with per-field confidence and a prohibited-content/shippability gate baked in.
2. Photos upload via `POST /uploads/listings` (random-filename S3, magic-byte content sniffing — `BR-UPLOADS-004`).
3. `POST /listings` — full creation. Server re-screens prohibited content and photo weapons/blur independently of the AI-assist step (`BR-LISTINGS-003`) and re-validates the taxonomy path server-side regardless of what the AI suggested.
4. **Price branch**: `price >= highValueThresholdCents` (default $2000) → `pending_approval`; otherwise → `approved` directly (unless the client explicitly requested `draft`).
   - **`pending_approval` branch**: an admin reviews via `GET /admin/listings` → `POST /listings/:id/approve` or `/reject` (admin-role-gated — `BR-LISTINGS-011`). Approve stamps `approvedAt`/`approvedById` and fires the saved-search-match + followed-seller-alert pipeline (the same pipeline a direct `approved` creation fires immediately).
   - **`approved`/`active` branch**: live immediately; saved-search matching (`Flow 9`) and follower notifications fire right away.
5. **Inventory seeding, implicit**: no explicit step — `Inventory` rows are seeded lazily from `Listing.stock` on first touch by any of `inventory`'s mutation primitives (`BR-INVENTORY-001`); a brand-new listing with no explicit inventory action yet still answers correctly via the `Listing.stock` fallback.

**Relist / pause / edit branches, same listing**:
- **Pause** (`PATCH /listings/:id/status`, `inactive`/`draft` from a live state) cancels every open offer with holds released (`BR-LISTINGS-004`-adjacent via the status-change side effect) and does **not** re-lock the commission rate on reactivation.
- **Relist** (`POST /listings/:id/relist`) creates a **new** listing via the same `createListing` path (fresh commission rate, re-screened photos) while the original is left completely untouched — confirmed gap: nothing requires the original to be `sold` first (`BR-LISTINGS-005`).
- **Edit** (`PATCH /listings/:id`) is hard-blocked once `status==='sold'` (`BR-LISTINGS-007`); a price edit crossing the high-value threshold either direction can demote to `pending_approval` or auto-restore to `approved` (`BR-LISTINGS-008`).

---

## Flow 4 — Offer negotiation → acceptance → order creation (the highest-risk flow in the system)

1. Buyer opens a listing, taps Make Offer → `POST /offers/preview` (no state created) shows the tax/shipping-inclusive total the buyer will actually authorize if they proceed — guaranteed to match what the real hold will charge (`BR-OFFERS-024`-adjacent, `calculateOfferTax` shared helper).
2. `POST /offers` — creates the offer **and** places a manual-capture payment hold on the buyer's card/wallet **at submission, before the seller has responded** (`BR-OFFERS-018`). Self-dealing (`BR-OFFERS-008`), one-open-offer-per-buyer-per-listing (`BR-OFFERS-009`), and amount-within-floor/ceiling (`BR-OFFERS-001`/`002`) are all enforced before the hold is created.
3. Seller sees the offer in their Seller Hub (`GET /offers?direction=incoming`, or web `sellerApi.getOffers()`). Negotiation is turn-based (`BR-OFFERS-005`):
   - **Counter** (either side, up to 3 times each, `BR-OFFERS-006`) re-authorizes a fresh hold at the new total before cancelling the old one, and restarts the 24h window (`BR-OFFERS-004`).
   - **Decline** releases the hold, no inventory/availability interaction at all.
   - **Cancel** (buyer-only, not turn-based) releases the hold and withdraws.
4. **Accept** (either side, whoever's turn it is) is the single highest-risk method in the codebase (`acceptOffer`, 15 ordered sub-steps documented in `modules/offers.md`):
   - Capture the hold (irreversible-without-a-refund) **before any database write**.
   - Create the `Order` directly through the orders repository (bypassing `OrdersService.create()`'s own guards — a documented, deliberate module-cycle-avoidance choice, meaning order-side guards like the mixed-seller-cart check do not apply to an offer-created order).
   - Flip the offer to `accepted` (the write a DB partial unique index protects against a concurrent duplicate accept, `BR-OFFERS-011`).
   - **Commit inventory** (`incrementCommitted`, confirmed unconditional on every successful accept — see `BR-OFFERS-012b` and `modules/offers.md`'s Correction callout).
   - Close every other open/unpaid-accepted sibling offer on the listing, with hold release and direction-aware notification copy (`BR-OFFERS-013`).
5. The resulting `Order` enters **Flow 5** (fulfillment) at `placed`, already paid — there is no separate "confirm payment" step for an offer-originated order (contrast Buy Now below).

**Known open gap in this flow**: a failed capture at step 4 leaves the offer completely unchanged with an immediate 400 — the client's confirmed 15-minute-retry-then-cancel resolution is not implemented (`BRI-297`, see `gaps-and-conflicts.md` § 2 #1).

---

## Flow 5 — Buy Now checkout → payment confirmation → order fulfillment

1. `POST /checkout/preview` — same shared tax helper as offers' preview, tolerant of a doomed cart (no throw on a bad item).
2. `POST /orders` — the second-highest-risk endpoint in the system. In order: listing existence+status, self-dealing guard (`BR-ORDERS-002`), single-seller-cart enforcement (`BR-ORDERS-003`), **live inventory check** (not static stock), address/payment-method ownership, offer-backed pricing snapshot if applicable, mid-checkout price-change guard (`BR-ORDERS-006`), per-item locked commission rate, **atomic inventory claim before any Stripe call** (15-min hold, `BR-ORDERS-004`), checkout-idempotency-keyed PaymentIntent creation, `Order.stripePaymentIntentId`'s DB-unique-constraint recovery on a race (`BR-ORDERS-005`).
3. **Two parallel completion paths, both writing the same `Payment` row** (`BR-PAYMENTS` cross-reference):
   - **Synchronous**: `POST /orders/:id/confirm-payment` (client-driven, for a saved card) — confirms the PaymentIntent server-side, finalizes inventory, closes competing offers on the sold listing only **after** the inventory decrement so availability reads are accurate (`BR-ORDERS` checkout section).
   - **Asynchronous**: the `payments` webhook's `payment_intent.succeeded` handler — the double-coverage path for a buyer whose app was killed mid-3DS-redirect (`BR-PAYMENTS-004`). Idempotent against replay via the `WebhookEvent` dedup table (`BR-PAYMENTS-002`).
4. If the hold is never confirmed within 15 minutes, the real BullMQ cron (`ReservationReleaseProcessor`, every minute) re-verifies Stripe directly before releasing the claim — never releases a hold whose PaymentIntent actually succeeded (`BR-ORDERS-004`).
5. Order proceeds through the seller fulfillment state machine: `placed → processing → packed → shipped → {out_for_delivery, delivered, returned}` (`BR-ORDERS-001`), driven by `PATCH /orders/:id/status` or the identical `PATCH /sellers/me/orders/:id/status`.
   - **Shipping** can go through the dedicated Buy-Shipping-Label flow (`POST /sellers/me/orders/:id/shipping-rates` → `POST /sellers/me/orders/:id/shipping-label`, real Shippo purchase, cross-order rate reuse explicitly blocked — `BR-SELLERS-015`) or a client-supplied tracking fallback via `PATCH /sellers/me/orders/:id/ship` (`BR-SELLERS-012`/`013`). The latter **bypasses `OrdersService.updateStatus`'s own state machine entirely** and must independently fire the buyer-notification (`BR-SELLERS-014`).
   - **Delivery** (`status → delivered`) decrements `Inventory.onHand` for every item, releasing the committed hold into a real sale, and stamps `deliveredAt` — the anchor both the 3-day buyer-confirm window and the 3-day dispute-report window count from.
6. **Receipt confirmation**: `POST /orders/:id/confirm-receipt` (buyer-only, `delivered`-only, blocked while a non-terminal dispute is active — `BR-ORDERS-013`) OR the 3-day lazy auto-confirm sweep (no cron — `BRI-516` open gap). Either path then eventually triggers `transferForOrder` (3-day additional hold window past delivery, `BR-CONNECT-011`) to actually pay the seller.

---

## Flow 6 — Order cancellation (three independent origins, one shared finalize path)

- **Buyer requests, pre-shipment only** (`POST /orders/:id/request-cancellation`, only while `placed|processing|packed` — `BR-ORDERS-010`). **Confirmed hidden from the current mobile UI entirely** (BRI-359, a deliberate client decision that a bought order is binding) — the endpoint is still fully live and must be exercised via a direct API call for testing.
  - Seller then `PATCH /sellers/me/orders/:id/approve-cancellation` or `.../deny-cancellation`.
  - Unanswered for 24h → auto-approves, but **lazily on next read only**, no cron (`BRI-516`-adjacent, no dedicated ticket found for this specific 24h sweep).
- **Seller cancels directly, immediate, no approval** (`POST /orders/:id/cancel`). Only `reason==='item_unavailable'` pauses the listing; `'damaged'` does not (`BR-ORDERS-011`, `BRI-614` open UX gap).
- **System auto-cancels after 7 days unshipped** (`maybeAutoCancelUnshipped`, lazy-on-read only, `BRI-591` open gap).

All three converge on `finalizeCancellation` (`BR-ORDERS` section): refunds via `ConnectService.refundOrder` **before** any order-row mutation (so a refund blocked by an open Stripe chargeback never leaves the order half-cancelled), releases the inventory hold, re-syncs the embedding index, and sends origin-specific notification copy.

---

## Flow 7 — Dispute (buyer claim, not a Stripe chargeback — see Flow 8 for that)

1. `POST /orders/:id/dispute` — buyer-only, `delivered`-only, within 3 days of `deliveredAt`, one per order (`BR-DISPUTES-002`). **Not blocked by a prior receipt confirmation** (`BRI-593` open gap, `BR-DISPUTES-014`). `Order.payoutHeld = true` immediately.
2. Seller evidence window, 24h, lazy-advance (`BR-DISPUTES-003`):
   - `PATCH /sellers/me/orders/:id/dispute/evidence` — submitting unconditionally flips to `awaiting_decision` regardless of remaining window time (`BR-DISPUTES-005`).
   - `PATCH /sellers/me/orders/:id/dispute/accept-return` — the RS1 shortcut, identical internal path to an admin approval (`BR-DISPUTES-006`).
   - No response in 24h → lazy auto-advance to `awaiting_decision` on next read.
3. Admin decides (`POST /admin/dispute-cases/:id/approve` or `/deny`, atomically claimed against a double-click/race — `BR-DISPUTES-007`).
   - **Deny** → payout hold released, buyer notified; seller never notified (`BRI-619` open gap).
   - **Approve** → a real Shippo return label is purchased (mock fallback only for genuinely-not-attempted cases; a real Shippo failure now hard-fails rather than faking a label — `BR-DISPUTES-008`).
4. Buyer ships the return. Refund triggers via **either** `POST /orders/:id/dispute/ship` (buyer's own tap — refunds immediately with **no carrier verification** for the mock-label case, which is every real dispute today, `BRI-594` open gap) **or** a real Shippo carrier-tracking webhook/poll — both converge on the same atomically-claimed `triggerReturnRefund` (`BR-DISPUTES-009`).
5. **On refund success** → dispute → `refunded` (terminal). **On refund failure** → dispute → `refund_failed`, every admin notified, **and the state is a confirmed dead end — no retry mechanism exists anywhere in the module** (`BR-DISPUTES-012`).
6. **If the buyer never ships within 5 days of approval** → `payoutHeld` auto-releases (lazy, no cron) but the dispute status stays `approved` indefinitely, invisible on the admin queue (which excludes `approved`) until a support agent looks it up by order id directly (`BR-DISPUTES-011`/`017`).

---

## Flow 8 — Stripe chargeback (`StripeDispute`, independent of Flow 7, can coexist on the same order)

1. The buyer files a chargeback with their bank → Stripe emits `charge.dispute.created` → `/payments/webhook` (platform-account event, **not** `/payments/webhook/connect` — Separate Charges & Transfers means Stripe never delivers these to the connect-scoped endpoint, `BR-CONNECT-010`) → dispatched into `ConnectService.onChargeDisputeCreated`.
2. Admin reviews via `GET /admin/stripe-chargebacks`; evidence submission itself happens in the **Stripe Dashboard**, not this API (confirmed — this is a documented, deliberate out-of-API boundary).
3. `charge.dispute.closed` (webhook) resolves the `StripeDispute` to `won`/`lost`/`warning_closed`.
4. A `lost`/`warning_closed` chargeback can be written off (`POST /admin/stripe-chargebacks/:id/write-off`) — **audit-trail only, does not release the payout hold** (`modules/admin.md`'s explicit finding).
5. `ConnectService.refundOrder` (used by Flow 6/7's cancellation/dispute refund paths) **blocks entirely** while an open `StripeDispute` exists on the order (`BR-DISPUTES-013`) — a buyer cannot get a dispute-flow refund on an order that's simultaneously under an active bank chargeback.

---

## Flow 9 — Saved search match → notification (listing-creation side effect)

1. A new listing transitions to live (`approved`/`active`, either at creation or via admin approval — Flow 3).
2. `SavedSearchesService.notifyMatches` is called (best-effort, swallowed on failure — never blocks listing creation, `BR-SAVED-SEARCHES-004`).
3. SQL pre-filters every `alertsEnabled` saved search whose structured facets are compatible, **excluding the listing's own seller from ever matching their own search** (`BR-SAVED-SEARCHES-003`).
4. The free-text `q` component is checked in-memory per candidate (`listingMatchesQuery`).
5. A `saved_search_match` notification fires per real match, and `SavedSearch.newMatchCount` increments.
6. Buyer later opens `GET /saved-searches/:id/results` (live-recomputed, never cached — `BR-SAVED-SEARCHES-002`) and/or `POST /saved-searches/:id/mark-viewed` to clear the badge.

---

## Flow 10 — Messaging, moderation, and blocking

1. **Conversation creation**: either `POST /conversations` (buyer-initiated, from a listing or directly to a seller) or `POST /sellers/me/orders/:id/conversation` (seller-initiated, order-anchored, the only way a seller originates a thread — `BR-MESSAGING-002`). Idempotent against a duplicate create for the same (buyer, seller, listing) triple.
2. **Message send** (`POST /conversations/:id/messages`) — content classification runs server-side: `payment`/`contact` text is hard-blocked and never persisted; profanity/bare-URL is flagged but delivered (`BR-MESSAGING-008`). A DB write (`$transaction`: insert message + bump conversation preview + increment unread) always happens before the gateway push attempt; the in-app `Notification` row always writes, only the push itself is conditionally suppressed if the recipient is actively viewing (`BR-MESSAGING-009`).
3. **Report** (`POST /conversations/:id/report`) creates an open `ConversationReport`, rate-limited to one-open-per-reporter-per-conversation. **Does not alter the conversation itself** — the message stream is unaffected until an admin acts.
4. **Admin moderation** (`GET /admin/conversation-reports` → `POST /admin/conversation-reports/:id/resolve`): `dismiss`/`warn`/`suspend`/`ban`, each a different real effect on `User.chatBanUntil`/`chatWarningCount` and an in-thread system message (visible to **both** participants, `BRI-562` gap). **No notification to the targeted user on any action** (`BR-MESSAGING-023`).
5. **Block** (either in-conversation `POST /conversations/:id/block` or standalone `POST /me/blocked-users/:userId`): soft-deletes the thread for the blocker, writes a `Block` row, and — as an explicit, silent, no-notification side effect — cancels every open offer between the pair (`BR-OFFERS-017`, `BR-MESSAGING-014`/`015`). A standalone block with `context==='buyer'` also unfollows the blocked seller if currently followed.

---

## Flow 11 — Account deletion request and purge

1. `GET /users/me/deletion` — live-computed eligibility (active orders both directions, pending payouts, open disputes — `BR-USERS-011`). `windowDays` is 30, or 60 if there's been financial activity in the last 30 days.
2. `POST /users/me/deletion/request` — blockers re-checked (not trusted from step 1), a 6-digit code emailed **synchronously-awaited** (unlike every sign-in OTP, a mail failure here is a real surfaced error — `BR-USERS-012`).
3. `POST /users/me/deletion/confirm` — blockers checked a **third** time, code burned in the same write that schedules deletion. **No attempt-lockout** on this code (`BR-USERS-013` gap). Account is **not** destroyed yet — only the window opens.
4. **Restoration, automatic**: any successful sign-in via email/password, OTP, or Google during the window cancels the scheduled deletion (`BR-AUTH-005`). **Confirmed NOT to happen for Apple/Facebook sign-in** (`BR-AUTH-014` gap). No mobile UI offers an explicit "cancel deletion" button — `DELETE /users/me/deletion` exists and works but has no frontend caller found.
5. **Purge, out-of-band**: an hourly BullMQ worker (`account-purge.processor.ts`, a **separate process**, never the API) re-checks blockers a **fourth** time per account, then scrubs the `User` row (name/email/username rewritten to non-PII placeholders, never deleted — `Order`/`Payout`/`Review` hold FKs to it), destroys disposable per-user data (addresses, payment methods, likes, searches, notifications, follow edges), and writes a 7-year-retained `DeletedAccountArchive` row for 1099-K/KYC substantiation. **Nothing ever deletes the archive row after 7 years** (`BRI-598`, open Backlog, confirmed by code — no purge-of-the-purge job exists).

---

## Flow summary table (entry point → primary modules touched)

| Flow | Entry point | Modules touched in order |
|---|---|---|
| 1. Sign-in/signup | `EmailEntry`/social buttons | auth → users |
| 2. Seller onboarding | Sell tab / Settings | sellers → connect |
| 3. Listing lifecycle | Sell flow | ai, uploads → listings → admin (review branch) → saved-searches, notifications |
| 4. Offer negotiation | Make Offer | offers → payment-methods (hold) → inventory → orders (order creation) |
| 5. Buy Now checkout | Checkout | orders → payments (webhook) → inventory → connect (payout) |
| 6. Cancellation | Order detail / Seller Hub | orders → sellers (approve/deny) → connect (refund) |
| 7. Dispute (internal) | Order detail claim | disputes → shipping (return label) → connect (refund) |
| 8. Chargeback | (bank-initiated) | payments (webhook) → connect → admin |
| 9. Saved-search match | (listing go-live) | saved-searches → notifications |
| 10. Messaging/moderation | Chat screen / Admin console | messaging → notifications |
| 11. Account deletion | Settings → Delete Account | users → (hourly worker, out-of-band) |
