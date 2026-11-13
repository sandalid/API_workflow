# Offers — lifecycle flows

## 1. Full negotiation lifecycle (happy path, no counters)

```
buyer                              API                                  seller
  |--POST /offers/preview--------->|  (optional — price-check UI)
  |<--{shippingCents,taxCents,...}-|
  |--POST /offers------------------>| createOffer:
  |                                  |   validate listing/self-deal/bounds
  |                                  |   validate card or verified wallet hold
  |                                  |   require address on file
  |                                  |   require no other open offer (this buyer, this listing)
  |                                  |   place manual-capture hold (card: new PI; wallet: verify existing PI)
  |                                  |   Offer row created, status=pending, expiresAt=+24h
  |                                  |   notify seller (push+email, best-effort)
  |<--201 OfferDto------------------|
  |                                  |                                      |--PATCH /offers/:id/accept-->|
  |                                  | acceptOffer:
  |                                  |   assertRespondable (seller's turn on a fresh pending offer)
  |                                  |   assertStillAvailable
  |                                  |   CAPTURE the hold (irreversible step, before any DB write)
  |                                  |   create Order (direct via OrdersRepository, NOT OrdersService.create)
  |                                  |   confirmOrderPayment (Payment row + mark listing sold-path)
  |                                  |   updateStatus -> accepted (DB unique-index backstop here)
  |                                  |   markOrdered (best-effort back-link)
  |                                  |   incrementCommitted (real inventory commit)
  |                                  |   cancelCompetingOffers + closeSiblingOffers (close any other offers on this listing)
  |                                  |   notify both parties (asymmetric copy depending on who acted)
  |<--200 OfferDto (orderId set)----|                                      |<--200 OfferDto (orderId set)-|
```

**Key fact**: there is no separate "pay now" step for the buyer anymore. Accept = capture = order-created = inventory-committed, all inside one synchronous call. This is a deliberate post-BRI-233 redesign; the old flow (accept, then a buyer "Pay $X" button, then checkout) is gone. A test suite inherited from that era (asserting a Pay button or a second checkout call after accept) is testing a flow that no longer exists.

## 2. Counter-negotiation lifecycle

```
buyer: POST /offers (amount=$35 on a $45 listing)                 -> pending, expires T+24h, buyer's turn gone (awaitingFrom=seller)
seller: PATCH /offers/:id/counter (amount=$39)                      -> countered, expires RESET to (counter-time)+24h, awaitingFrom=buyer
                                                                        hold replaced: new PI for $39+shipping+tax authorized FIRST, old PI cancelled after
buyer: PATCH /offers/:id/counter (amount=$32)                       -> countered, expires reset again, awaitingFrom=seller
                                                                        hold replaced again, same new-then-cancel-old ordering
seller: PATCH /offers/:id/accept                                    -> accepted at $32 (the agreed price, honoured even if listing price changed since)
                                                                        capture happens against the THIRD (buyer's own) hold, which is already sized correctly
```

Counter cap: each party gets 3 counters. If both sides use all 3, the 7th response attempt (whoever's turn it is) can only Accept or Decline — `countersRemaining: 0` on the DTO for that party; the API itself rejects a 4th counter from the same party with a 400.

Wallet-originated offers cannot be countered past the FIRST hold — any counterOffer call against a wallet-backed offer (`offer.paymentMethodId == null`) is rejected outright (400), regardless of whose turn it is or which round. The only path forward for a wallet offer the counterparty wants to negotiate is: decline it, and the buyer sends a fresh offer (and fresh wallet authorization) at the new price.

## 3. Decline / cancel (withdraw) / expire — the three non-accept terminal paths

- **Decline** (seller or buyer, whichever has the turn): hold released, offer -> `declined`, notify the other party. No availability check (a dead offer costs the declining party nothing).
- **Cancel/withdraw** (buyer only, any time the offer is still open — NOT turn-gated): hold released, offer -> `cancelled` with `reason: 'withdrawn'` in its closing history entry, notify seller. This is the one verb a seller cannot call on their own offers.
- **Expire** (neither party acts within the window): settled lazily — the FIRST subsequent `GET /offers` call by either party (not a background job) flips the row via `expireOne`'s `updateMany` (itself the concurrency guard against both parties' lists loading at once), releases the hold, and notifies whoever was left waiting (the actor of the last history entry). Until that read happens, the row still reports `pending`/`countered` everywhere, including on the Admin Offers page (`BRI-535`, still open).

## 4. System-initiated cancellation paths (no human tapped a button)

Four distinct triggers, all converging on the same "cancelled, hold released, buyer notified" shape, but reached through different code paths:

| Trigger | Method | Scope | Notifies | Distinguishing reason stamped |
|---|---|---|---|---|
| A competing offer on the same listing is accepted and the sale exhausts the listing | `cancelCompetingOffers` (called from `acceptOffer` and from `OrdersService.confirmPayment`/the Stripe webhook, for a Buy Now sale) | every unpaid offer on that one listing | buyer (vague — "sold to another buyer" — unless the losing buyer IS the one who bought, see BR-OFFERS-013) + seller (named: "@buyer bought X, so N offers were closed") | `sold_to_other` / `bought_yourself` / `lost_after_accept` |
| Same, but the earlier `cancelCompetingOffers` pass didn't catch it for some reason (multi-unit edge, or a failed sweep) | `closeSiblingOffers` (always runs at the end of `acceptOffer`, unconditional catch-all) | every still-unpaid offer on that listing | buyer only ("this one got away") | none (always `sold_to_other`-shaped copy, no `reason` field recorded) — **and does NOT release the Stripe hold, see BR-OFFERS-023** |
| Listing deleted / paused / re-priced across the $2,000 review threshold | `cancelOpenOffersForListing`, triggered via the `LISTING_OFFERS_CANCEL_EVENT` event emitted by the listings module (event, not a direct injected call, to avoid a require-time module cycle) | every open (pending/countered) offer on that listing | buyer, reason-specific copy naming what the seller did | `listing_deleted` / `listing_paused` / `listing_price_review` |
| Buyer and seller block each other | `cancelOffersBetween`, called from the messaging/users block-handling path | every open offer between that exact pair, across ALL their shared listings | nobody (silent by design) | none recorded |

## 5. Accepted-offer -> Order handoff (where "an offer becomes an order")

This is the one place offers and orders genuinely intersect at the write layer, and it is NOT routed through `OrdersService.create()`:

- `OffersService.acceptOffer` calls `this.ordersRepo.createWithItems(...)` **directly** (`offers.module.ts` documents this as a deliberate repository-level reach to avoid a third module import cycle on top of the existing Offers↔Payments `forwardRef`).
- This means none of `OrdersService.create()`'s own validation (e.g. its mixed-seller-cart rejection, any checks added there later that aren't duplicated in `acceptOffer`) applies to an offer-created order. The two creation paths are genuinely parallel code, not funneled through one service — a change to `OrdersService.create`'s business rules does NOT automatically apply to an offer-accepted order, and vice versa.
- The created Order carries `stripePaymentIntentId: offer.paymentIntentId` (the same PI that was just captured) and `items: [{ listingId, price: offer.amountCents, shippingPrice: offer.shippingCents ?? FLAT_SHIPPING_RATE_CENTS, quantity: 1 }]` — always exactly one item, one quantity (an offer is always on a single unit).
- `OrdersService` has its own READ-side awareness of offer-backed orders: `OrdersService.create`'s cart-checkout path (a DIFFERENT, buyer-initiated flow for buying an *already-accepted* offer through the normal cart, used when `item.offerId` is present in the cart) independently re-validates the offer (`offer.buyerId === userId && offer.status === 'accepted'`) and prices the cart line from the offer's own snapshot (`offerPriceMap`/`offerShippingMap`) rather than the listing's live price. This is a SEPARATE path from `acceptOffer`'s own direct order-creation and exists for a buyer who reaches checkout via the cart with an offerId attached rather than through the atomic accept call — worth testing both ways a reader can arrive at a paid order for an accepted offer.
- `markOrdered([offerId], order.id)` stamps `Offer.orderId` — this is the "already paid, hide the Pay button" signal read by `toDto`'s `orderId` field, by the mobile `OfferThread`'s "View order" button, and by the web seller offers table's "Ordered" badge. It is explicitly best-effort (a failure here is logged, not thrown) — the Order row itself remains the source of truth even if this back-link write fails.

## 6. What does NOT exist (confirmed by reading the code, not inferred)

- No `GET /offers/:id` — all detail is derived client-side from the `GET /offers` list.
- No scheduled/background expiry sweep — confirmed via repository doc comments stating "there is no scheduler in the API," and via `BRI-535` still sitting in Backlog.
- No capture-failure retry window — confirmed via `BRI-297` still sitting in Backlog and the code's immediate-throw-on-capture-failure behavior.
- No admin-side mutate endpoints for offers in this module (accept/decline/counter/cancel as an admin override) — admin's own offers surface (`GET /admin/offers`) is read-only, a separate endpoint in the `admin` module.
- No idempotency key on the mutating PATCH endpoints themselves (accept/decline/counter/cancel) at the HTTP layer — the createOffer/wallet-hold-intent hold-creation calls to Stripe ARE idempotency-keyed (`buildOfferHoldIdempotencyKey`, 10s bucket), but a duplicate PATCH request (e.g. a double-tapped Accept) is NOT deduplicated by a request-level idempotency key — it is caught instead by the business-state check (`assertRespondable` rejects a second accept because status is no longer pending/countered) and, in the genuine-race case, by the DB unique index. This is a narrower guarantee than true idempotency: the SECOND request in a race is rejected with an error, not silently deduplicated to return the same success response as the first.
