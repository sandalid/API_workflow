# Module: orders

**Scope**: `apps/api/src/orders/` — controller, service, repository, DTOs, the Buy-Now reservation-release BullMQ processor. 13 HTTP endpoints (of this batch's 24; the other 11 are `disputes`, see `disputes.md`).

Source files traced in full:
- `apps/api/src/orders/orders.controller.ts`
- `apps/api/src/orders/orders.service.ts` (1877 lines — read in full, two passes)
- `apps/api/src/orders/orders.repository.ts`
- `apps/api/src/orders/reservation-release.processor.ts` + `reservation.constants.ts`
- `apps/api/src/orders/dto/*.ts` (all 8 DTOs)
- Cross-module reads (not re-analyzed as their own module, only for order-flow context): `apps/api/src/connect/connect.service.ts` (`refundOrder`/`reverseTransferIfNeeded`, lines ~1208-1322), `apps/api/prisma/schema.prisma` (`Order`, `OrderItem`, `OrderStatusHistory`, `Payment`, `Payout`, `Inventory`, enums `OrderStatus`/`PaymentStatus`/`PayoutStatus`).

## Guard/auth summary

Class-level `@UseGuards(JwtAuthGuard)` on `OrdersController` (`orders.controller.ts:31`) — every route requires a logged-in user; no public routes in this controller. Two routes add `@UseGuards(RolesGuard) @Roles('SELLER')`:
- `POST /orders/:id/cancel` (`:140-141`)
- `PATCH /orders/:id/status` (`:153-154`)
- `GET /seller/orders` (`:165-166`)

`RolesGuard`'s `'SELLER'` check is live-DB (`UsersService.findRawById`, per `apps/api/CLAUDE.md`), not JWT-claim-based — a user whose seller status changes mid-session is re-checked every request.

**Important cross-module note**: `OrdersService.approveCancellation`/`denyCancellation` exist on the service (`orders.service.ts:1534-1561`) but are **not exposed by `OrdersController`** — they're wired into `sellers.controller.ts` instead: `PATCH /sellers/me/orders/:id/approve-cancellation` and `PATCH /sellers/me/orders/:id/deny-cancellation` (`apps/api/src/sellers/sellers.controller.ts:242-262`). Those two routes are out of this batch's assigned 24 and belong to whichever agent covers the `sellers` module, but they are load-bearing for the cancellation-request flow documented below — cross-reference, don't re-analyze. Similarly `PATCH /sellers/me/orders/:id/status` (`sellers.controller.ts:230-240`) calls the **exact same** `OrdersService.updateStatus` as this module's `PATCH /orders/:id/status` — two routes, one service method, no divergence found.

## Order state machine (verified against Prisma schema)

`enum OrderStatus` (`schema.prisma:78-87`): `placed | processing | packed | shipped | out_for_delivery | delivered | cancelled | returned`. **No separate "paid"/"completed"/"confirmed" status** — payment state lives on the related `Payment.status` (`processing|succeeded|failed|refunded|partially_refunded|canceled`), and "buyer confirmed / order complete" is the boolean/timestamp pair `Order.receiptConfirmedAt`/`receiptAutoConfirmed`, not a status value. A completed order's `status` stays `delivered` forever (or becomes `returned` via the dispute refund path) — `isCompleted` on the client is computed, not read off `status` alone (`OrderDetail.tsx:373-374`: `status === 'delivered' && receiptConfirmed || status === 'returned'`).

Seller-driven forward transitions (`ALLOWED_TRANSITIONS`, `orders.service.ts:105-125`):
```
placed -> processing
processing -> packed
packed -> shipped
shipped -> out_for_delivery | delivered | returned   (BRI-414: carrier return-to-sender)
out_for_delivery -> delivered | returned
delivered -> returned
cancelled -> []   (terminal)
returned -> []    (terminal)
```
`cancelled` is never a seller-selectable forward target through this table — it's reached only via `cancelOrder`/`requestCancellation`+approve/auto-approve, or the reservation-release/seller-never-shipped sweeps. `SELLER_ALLOWED_STATUSES` (`:45`) additionally restricts which values the DTO's `@IsEnum(OrderStatus)` (which accepts all 8) can actually reach via `PATCH /orders/:id/status`: `processing|packed|shipped|out_for_delivery|delivered|returned` — `placed` and `cancelled` are rejected even before the transition-table check (`updateStatus`, `:1340-1342`).

`applyAdminStatusChange` (admin path, called from `AdminService` — cross-ref, not this batch) **deliberately bypasses `ALLOWED_TRANSITIONS`** but still writes the `OrderStatusHistory` row, stamps `deliveredAt`, and runs `releaseInventoryForStatus` — this was itself a fixed bug (see `prisma/manual-sql/2026-08-31-repair-leaked-inventory-holds.sql` and BRI-532/BRI-528 in Linear, both admin-side).

## Checkout → order creation (the money-critical path)

`POST /checkout/preview` (`:36-43` → `preview()`, `orders.service.ts:151-241`) and `POST /orders` (`:46-53` → `create()`, `:285-635`) **must never disagree on a number** — `calculateOrderTax` (`:252-283`) is the single shared helper both call, fixed after BRI-363 found the two paths drifting. Key invariants proven by reading `create()` line-by-line:

1. **Listings existence + status check** (`:293-308`): all `listingIds` must resolve, cart must be non-empty (`ArrayNotEmpty` in the DTO is the first line of defense, `:300-302` the belt-and-braces service check), every listing must be `active|approved|reserved`.
2. **Self-dealing guard — BRI-72, verified live** (`:309-316`): `found.some(l => l.sellerId === userId)` → `403 ForbiddenException('You cannot purchase your own listing')`. This is the authoritative server-side guard; `apps/mobile/CLAUDE.md`'s own BRI-72 note confirms a *client-side* UX gap existed (a stale closure in `useAuthGate`'s resume path could let a seller reach Buy Now on their own listing through guest sign-up) but states the API guard already 403s it — confirmed directly in this read, this is not a security hole, only a historical UX gap.
3. **Single-seller cart enforced** (`:317-326`): mixed-seller carts are rejected (`400`) because one Order/PaymentIntent/payout is attributed to `found[0].sellerId`.
4. **Live inventory check, not static stock** (`:327-357`): `available = onHand - committed - unavailable` per listing (`InventoryRepository`), not `Listing.stock`. An offer-backed item that lost the stock race gets a distinct, more informative `409` message than a plain Buy Now ("…your accepted offer was closed. You have not been charged.").
5. **Address/payment-method ownership** (`:359-373`): both must belong to `userId`; a saved card must be on `isSupportedCardBrand` allowlist (BRI-238).
6. **Offer-backed pricing snapshot** (`:381-407`): if `item.offerId` is set, price and shipping come from the `Offer` row (`amountCents`/`shippingCents`), never the listing's live price — this is what `preview()` also does (BRI-445), so the two can't disagree.
7. **Mid-checkout price-change guard — BRI-639** (`:409-427`): a Buy Now item carries `expectedPriceCents` (the price the buyer saw when checkout began); if the listing's current `price` differs, `409 ConflictException`. Offer-backed items are exempt (already locked to `offer.amountCents`).
8. **Commission computed per item at that item's own locked `commissionRateBps`** (`:462-471`, BRI-352) — a cart mixing listings created under two different platform commission rates keeps each its own rate; never one blended rate.
9. **Tax/shipping never flow to the seller** (`:472-479`, BRI-363): `sellerAmount = subtotal - platformFeeAmount - discount`. Redspur is the marketplace facilitator of record for sales tax.
10. **Atomic inventory claim BEFORE any Stripe call** (`:481-501`, BRI-79/BRI-818): `inventory.commitForReservation(listingId, qty, holdExpiresAt)` per item; on any item's claim failing, every already-claimed item in the same multi-item cart is rolled back (`releaseReservationClaim`) before the `409` is thrown. `holdExpiresAt = now + RESERVATION_HOLD_MS` (15 min, `reservation.constants.ts:18`).
11. **Checkout idempotency** (`:506-543`, `buildCheckoutIdempotencyKey`, `:87-100`): keys Stripe's `createPaymentIntent`/`createUnconfirmedPaymentIntent` call off `userId + sorted cart fingerprint + addressId + paymentMethodId + a 10-second time bucket`. A genuine re-order of the identical cart minutes later gets a real second charge (bucket rolled over); a double-tap/retry within the same 10s window reuses the same PaymentIntent.
12. **`Order.stripePaymentIntentId` is `@unique`** (`schema.prisma:1093`, added via `prisma/manual-sql/2026-09-06-add-order-payment-intent-unique.sql` — a **live QA-found bug fix**: two near-simultaneous checkouts correctly reused one PaymentIntent but nothing stopped two `Order` rows for it, stranding the loser at `placed` forever). `create()`'s catch block (`:589-615`) turns the `P2002` into "return the winner's existing order" instead of a 500, and releases the loser's redundant inventory claim.
13. Buy-Now hold release is a **real BullMQ cron** (`ReservationReleaseProcessor`, every minute, `reservation.constants.ts:28`) — re-checks Stripe directly before releasing (never cancels a hold whose PaymentIntent actually succeeded), distinct from every other "sweep" in this file which is lazy-on-read with no cron at all (see below).

`confirmPayment` (`:637-714`): confirms the PaymentIntent server-side for a saved card, finalizes inventory (clears the hold on success, releases the claim and sets `cancelled` on a definitive failure), and — load-bearing ordering — **closes every other open offer on the sold listing(s) only after** the inventory commit/decrement loop, so `OffersService.cancelCompetingOffers` sees accurate availability (BRI-270, BRI-258's missing second trigger path).

## Cancellation (two independent paths, three endpoints, two controllers)

- **Buyer requests** (`POST /orders/:id/request-cancellation`, `:127-135` → `requestCancellation`, `orders.service.ts:1494-1514`): only while `BEFORE_SHIPPED_STATUSES` (`placed|processing|packed`, `:50`) — once a tracking number exists, cancellation is off the table (spec: "before tracking upload", not a flat day count). Sets `cancelRequestedAt/By/Reason`; seller gets a notification saying "respond within 24h or it auto-approves."
- **Seller approves/denies** — endpoints live in `sellers.controller.ts` (see cross-module note above), calling `OrdersService.approveCancellation`/`denyCancellation` (`:1534-1561`), which both require `order.cancelRequestedAt` to be set and both delegate the actual state change to the shared `finalizeCancellation` (approve only) — deny just clears the request and notifies the buyer.
- **Seller cancels directly** (`POST /orders/:id/cancel`, `:138-148` → `cancelOrder`, `:1522-1532`): no approval step, immediate. `reason === 'item_unavailable'` additionally flips the listing to `inactive` (prevents auto-relist inviting another unfulfillable sale) — `damaged` does not, so the listing silently returns to sale via the inventory-release-driven `available` recompute (BRI-614 flags this as a UX gap: no confirm step before the immediate cancel+refund, and only one of the two reasons pauses the listing — both still true as read).
- **24h buyer-request auto-approve** (`maybeAutoApproveCancellation`, `:902-917`) is **lazy-on-read only** — no cron. Checked on `findById`/`findAllByBuyer`/`findAllBySeller`. If nobody opens the order or list past the 24h window, the request sits unresolved indefinitely. (Matches Linear BRI-516's sibling concern for receipt auto-confirm; no equivalent ticket found specifically for this one but the mechanism and the gap are identical — see `gaps.md`.)
- **`finalizeCancellation`** (`:1571-1678`) is the single choke point for all three cancellation origins (`seller_direct|buyer_request_approved|seller_never_shipped`). It:
  - Detects and blocks the **webhook-race window** (`:1588-1592`): a cancel attempted in the seconds between `create()` returning and the `payment_intent.succeeded` webhook landing would otherwise refund `null` (ambiguous with "already fully refunded") and proceed to cancel an order that *was* actually charged, with no automatic recovery. Now throws a retryable `400` instead.
  - Refunds via `ConnectService.refundOrder` **before** any order-row mutation (so a refund blocked by an open Stripe chargeback — `refundOrder`'s own guard — never leaves the order half-cancelled with no pending request to retry).
  - Releases the committed inventory hold and re-syncs the embedding index.
  - Sends differently-worded notifications per initiator (`seller_direct` notifies both sides; `seller_never_shipped` and `buyer_request_approved` notify the buyer only — **seller is never notified of their own `seller_never_shipped` auto-cancel's actual completion beyond this one message**, consistent with BRI-619's sibling gap on the disputes side).

**Mobile-side finding (BRI-359, confirmed live in code, not stale)**: `apps/mobile/src/screens/profile/OrderDetail.tsx` has the ENTIRE buyer-initiated "Request Cancellation" UI commented out (`:57-80`, `:104-108`, `:207-236`, `:357-362`, `:783-809`) — a bought order is now treated as binding per client decision (22 Sep 2026). The API's `request-cancellation` endpoint, `CancelOrderModal.tsx`, and `requestCancellation()` in `ordersApi.ts` are all still fully live/callable — just unreachable from the current mobile UI. **A tester must call `POST /orders/:id/request-cancellation` directly** (Postman/API client) to exercise this flow at all on the current build; no mobile screen reaches it. See `gaps.md`.

## Delivery / confirm-receipt / resell

- `updateStatus` → `delivered` stamps `Order.deliveredAt` (`orders.repository.ts:219-222`) in the same transaction as the status write — this is the anchor both the buyer's 3-day confirm window and the dispute-reporting 3-day window count from (previously approximated with `updatedAt`, which any unrelated write silently reset).
- `POST /orders/:id/confirm-receipt` (`:68-75` → `confirmReceipt`, `orders.service.ts:1171-1200`): buyer-only, requires `status === 'delivered'`, not already confirmed, **and no active dispute** (`hasActiveDispute`, mirrors mobile's `isActiveDispute`/`TERMINAL_DISPUTE_STATUSES` — both sides agree `denied|withdrawn|refunded` are terminal, `approved` is NOT terminal because the refund hasn't settled and the payout must stay held). Uses a compare-and-set repository call (`setReceiptConfirmed`, `:297-303`) so a buyer tap racing the 3-day auto-confirm sweep can't double-stamp.
- **3-day auto-confirm** (`maybeAutoConfirmReceipt`, `:1215-1233`) and the **retry-transfer safety net** (`maybeRetryTransfer`, `:1274-1277`, closing a real gap where a buyer confirming promptly — the common case — hit the transfer-hold window and nothing ever called `transferForOrder` again) are both lazy-on-read, no cron. Linear **BRI-516** ("Auto-complete delivered orders… without anyone opening the order") documents this exact gap as still open/backlog.
- **7-day seller-never-shipped auto-cancel** (`maybeAutoCancelUnshipped`, `:934-949`, `SHIP_WINDOW_MS`): also lazy-on-read. Linear **BRI-591** documents the identical open gap ("only runs when someone reads the order… if nobody opens it, the order stays open past day 7").
- `GET /orders/:id/resell-prefill` (`:102-108`): buyer-only, `delivered`-only, first line item only (orders are effectively single-item today per the doc comment).

## Order number / history / receipt

- User-facing order number = last 8 chars of the id, upper-cased — single source `apps/mobile/src/utils/orderNumber.ts`, matched server-side by the literal `id.slice(-8).toUpperCase()` used throughout `orders.service.ts`'s notification bodies and the PDF receipt (`:1721,1737`). **BRI-669 / REDB1-82**: three Seller Hub screens previously had their own 5-char copy — ticket status is `QA Passed` in Linear (fixed), confirmed consistent in the code read here.
- `GET /orders/:id/history` (`:93-99`): parses the `cancelled` row's description into a structured `cancelReason` key server-side (`parseCancelReason`, BRI-271) — buyer and seller render **different label text from the same key** (`apps/mobile/src/utils/cancelReason.ts` for the buyer; a separate seller-sheet copy for the seller) — by design, not a bug, per the doc comments on both sides.
- `GET /orders/:id/receipt` (`:111-124`): PDF via `pdfkit`, buyer-or-seller only. No DTO (none needed — path param + ownership check only).

## Endpoint-by-endpoint summary

| Endpoint | Guard | Key business rules | Notes |
|---|---|---|---|
| `POST /checkout/preview` | JWT | Same tax/pricing math as `create()` (BRI-363/BRI-445); tolerant of a doomed cart (no throw on bad offer) | No idempotency key here — it's read-only |
| `POST /orders` | JWT | Self-dealing guard, single-seller cart, live inventory, price-change guard, idempotent PaymentIntent, unique constraint recovery | The highest-risk endpoint in this module — see Test Plan |
| `POST /orders/:id/confirm-payment` | JWT, buyer-owns-order | Reservation-expiry race handling; closes competing offers | |
| `POST /orders/:id/confirm-receipt` | JWT, buyer-owns-order | Blocked while dispute active; CAS against auto-confirm sweep | |
| `GET /me/orders` | JWT | Paginated; runs every lazy sweep per page before serializing | `page`/`limit` capped 1-100 |
| `GET /orders/:id` | JWT, buyer-or-seller | Runs every lazy sweep (cancel auto-approve, ship-timeout, receipt auto-confirm, carrier poll, transfer retry) | |
| `GET /orders/:id/history` | JWT, buyer-or-seller | Parses cancel reason key server-side | |
| `GET /orders/:id/resell-prefill` | JWT, buyer-only | `delivered`-only | |
| `GET /orders/:id/receipt` | JWT, buyer-or-seller | PDF stream | |
| `POST /orders/:id/request-cancellation` | JWT, buyer-owns-order | Pre-shipment only; mobile UI hides this (BRI-359) | Still fully live server-side |
| `POST /orders/:id/cancel` | JWT + RolesGuard(SELLER) | Immediate, no approval; `item_unavailable` pauses listing | |
| `PATCH /orders/:id/status` | JWT + RolesGuard(SELLER) | `ALLOWED_TRANSITIONS` + `SELLER_ALLOWED_STATUSES` | Same service method as `sellers.controller.ts`'s `/sellers/me/orders/:id/status` |
| `GET /seller/orders` | JWT + RolesGuard(SELLER) | Paginated, optional `status` filter | `status` query param is an unvalidated `string`, not `@IsEnum(OrderStatus)` — see `gaps.md` |

See `qa-knowledge/fragments/orders-disputes.*` for the structured business-rules/test-scenarios/dependency-map/gaps/flows/endpoint-status extracted from this reading, shared with `disputes.md`.
