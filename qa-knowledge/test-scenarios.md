# Test Scenarios

**Scope note**: 352 business rules and 80+ gaps/conflicts were catalogued across 288 endpoints (see `business-rules.json`, `gaps-and-conflicts.md`). Deriving a fully exhaustive scenario set for every endpoint (valid + every validation boundary + every auth/ownership combination) would run into the thousands of entries. This file instead derives **every scenario directly implied by a business rule, a confirmed gap, or a code/ticket conflict** — i.e., every scenario here is traceable to a specific rule id and has a reason to exist beyond generic CRUD coverage. Routine "valid create / 401 without a token / 400 on a missing required field" scenarios for simple, low-risk endpoints (most of `categories`, `brands`, `materials`, `health`, `recent-searches`, simple admin list reads, etc.) are not individually enumerated — the pattern is identical and low-value to restate 250 times; `gaps-and-conflicts.md` § "genericPatterns"-equivalent reasoning in `dependency-map.json` covers the setup shape once.

**Source-of-expectation legend**, used in every scenario's "Expected" column:
- **[CODE]** — the expected result is read directly from the implementation; this is testing *current, implemented* behavior.
- **[TICKET]** — the expected result comes from a Linear ticket's stated acceptance criteria, where code and ticket agree.
- **[CODE≠TICKET]** — code and ticket disagree; the scenario is written against the CODE's actual behavior, with the ticket's stated expectation noted as the open question. Never invented — see `gaps-and-conflicts.md` § 3 for the specific conflicts.
- **[GAP]** — there is no defined expected behavior because the control simply doesn't exist; the scenario documents the absence itself as the thing to confirm.

---

## Auth & Identity

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-AUTH-001 | `POST /auth/login` | BR-AUTH-003 | A real account | anon | Login with wrong password, then with a non-existent email | Both return the identical `401 'Invalid credentials.'` body | [CODE] |
| TS-AUTH-002 | `POST /auth/login` | BR-AUTH-004 | A suspended account | anon | Login with correct credentials | `401 'Account suspended.'`, not 200 | [CODE] |
| TS-AUTH-003 | `POST /auth/otp/request` | BR-AUTH-007/008 | An account with 5 prior failed OTP attempts (lockout active) | anon | Request a new OTP | `429 OTP_LOCKED` — the lockout is checked BEFORE a new code is issued, not reset by the new request | [CODE] |
| TS-AUTH-004 | `POST /auth/otp/request` | BR-AUTH-008 | 3 resends already sent for the current code cycle | anon | Request a 4th resend | `429 OTP_COOLDOWN`, 15-minute cooldown starts | [CODE] |
| TS-AUTH-005 | `POST /auth/otp/verify` | BR-AUTH-010 | A fresh OTP code | anon | Submit a wrong code 5 times | 5th attempt deletes the code row AND starts/escalates `OtpLockout`; the (now-deleted) correct code can never succeed afterward even if resubmitted | [CODE] |
| TS-AUTH-006 | `POST /auth/otp/verify` | BR-AUTH-011 | A brand-new email, a requested username already taken by another account | anon | Verify with that `username` in the body | `409 USERNAME_TAKEN` — not silently suffixed | [CODE] |
| TS-AUTH-007 | `POST /auth/social/google` | BR-AUTH-012 | An existing account created via email/OTP with email `x@y.com` | a Google ID token asserting the same `x@y.com` | Call the endpoint | `409 'An account already exists for this email. Sign in with email instead.'` — no silent linking | [CODE] |
| TS-AUTH-008 | `POST /auth/social/apple` | BR-AUTH-014 | A buyer account mid-deletion-window | Apple token for that account's email, account not suspended | Sign in | `accountRestored` is **absent/null** in the response and `deletionScheduledFor` is NOT cleared — **[GAP]**, contrast `TS-AUTH-009` | [CODE] (gap) |
| TS-AUTH-009 | `POST /auth/login` | BR-AUTH-005 | Same setup as TS-AUTH-008 but via email/password | same account | Sign in | `accountRestored` populated, deletion cancelled — confirms the asymmetry is real, not a misreading | [CODE] |
| TS-AUTH-010 | `POST /auth/refresh` | BR-AUTH-019 | A valid, already-revoked refresh token (e.g. reuse an old rotated-away token) | — | Call refresh with it | `401`, AND the entire rotation family is revoked — verify a SUBSEQUENT call with the (until-now valid) current token in that family also now fails | [CODE] |
| TS-AUTH-011 | `POST /auth/sessions/revoke-others` | BR-AUTH-023 | A legacy/admin-style token with no `sid` | that token | Call the endpoint | `400 'Please sign in again to manage your devices.'` — not a 500, not a silent no-op | [CODE] |
| TS-AUTH-012 | `DELETE /auth/sessions/:id` | BR-AUTH-024 | Two accounts, each with a live session | Account A's token, Account B's `familyId` | Attempt to revoke it | `404` — identical to an unknown id, never `403` | [CODE] |
| TS-AUTH-013 | `GET /auth/dev/otp` | — | Any environment | anon | Call with `NODE_ENV=production` | `404` unconditionally, before the service even checks for a pending code | [CODE] |
| TS-AUTH-014 | `POST /auth/change-password` | BR-AUTH-025 | An account signed in on 2 devices (2 refresh-token families) | device A | Change password successfully | Device A's own session dies (local logout call); device B's session is **unaffected**, neither server-side nor client-side — **[GAP]** | [CODE] (gap) |

## Users

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-USERS-001 | `PATCH /users/me` | BR-USERS-002 | An account with `phone` set | self | Send `{ phone: "" }` | Phone is cleared to `null` (explicit empty-string-clears semantics, distinct from omitting the field) | [CODE] |
| TS-USERS-002 | `PATCH /users/me/preferences` | BR-USERS-005 | A fresh account, `prefsSkipped: true` | self | Save `{ personalizedRecommendations: true }` only (no facets) | `prefsSkipped` stays `true` — only a real shopping-facet clears it | [CODE] |
| TS-USERS-003 | `PATCH /users/me/preferences` | BR-USERS-006 | An account with `notifications.priceDrops: false` already saved | self | Save `{ notifications: { offersMessages: false } }` (omitting `priceDrops`) | `priceDrops` remains `false` (preserved, not reset to a default) | [CODE] |
| TS-USERS-004 | `PATCH /users/me/preferences` | BR-USERS-008 | — | self | Toggle a notification preference, leave the screen, reopen it | **[CODE≠TICKET]**: code shows the merge persists correctly (unit-tested); `BRI-521`/`REDB1-40` are Reopened in Linear. Run this as a real device/runtime test specifically to determine whether the ticket describes a residual client race not covered by the code fix, or is stale. | conflict |
| TS-USERS-005 | `POST /users/me/push-token` | BR-USERS-009 | Same Expo token registered on account A | account B | Register the identical token | Token is atomically detached from A and attached to B in one transaction — verify A's subsequent push attempts do NOT reach the device | [CODE] |
| TS-USERS-006 | `POST /users/me/deletion/confirm` | BR-USERS-013 | A valid pending deletion code | self | Submit the wrong code 20+ times in rapid succession | No lockout triggers — only the global 100/min throttle eventually limits it; the 20th wrong guess is processed identically to the 1st — **[GAP]** | [CODE] (gap) |
| TS-USERS-007 | `GET /users/:id` | BR-USERS-017 | A suspended account | anon | Fetch its public profile | `200`, `isSuspended: true` in the body — NOT a 403/404 | [CODE] |
| TS-USERS-008 | `POST /users/:id/follow` | BR-USERS-020 | A suspended seller account | a different buyer | Attempt to follow | `404`, not `403` — existence is not confirmed to the follower | [CODE] |
| TS-USERS-009 | `POST /users/:id/follow` then `DELETE .../follow` racing | BR-USERS-021 | A seller account | one buyer, two near-simultaneous requests (follow then unfollow within the same network round-trip window) | **[GAP]**: no server-side serialization exists for this race — the final state depends on which request's write lands last, not tap order. Mobile mitigates this client-side; a non-mobile caller (direct API test, web, a script) is NOT protected. This is the single highest-value concurrency scenario to actually run against a live environment. | gap-confirmed-by-code |
| TS-USERS-010 | `POST /users/:id/report` (mobile UI path) | BR-USERS-022 | A seller's shop page | buyer, via the mobile app's "Report" menu | Tap Report, confirm | **[GAP]** (mobile-only, not an API scenario): the UI shows success but makes NO network call — confirm via network-traffic capture during a mobile UI test, not via a direct API call (the API itself works fine when called directly, per the web-portal caller) | gap-confirmed-by-code |

## Offers (highest-risk money/state-machine module)

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-OFFERS-001 | `POST /offers` | BR-OFFERS-008 | A seller's own live listing | that same seller | Attempt to make an offer on it | `400` | [CODE] |
| TS-OFFERS-002 | `POST /orders` (Buy Now) | BR-ORDERS-002 | Same listing | that same seller | Attempt to Buy Now | `403` — **confirm the two self-dealing checks for the identical business rule use different HTTP statuses (400 vs 403)**, cross-referenced against TS-OFFERS-001 | gap-confirmed-by-code (inconsistency, not a defect in either alone) |
| TS-OFFERS-003 | `POST /offers` | BR-OFFERS-009 | An existing open (`pending`) offer from buyer B on listing L | buyer B | Submit a second offer on L | `400` — one open offer per buyer per listing | [CODE] |
| TS-OFFERS-004 | `POST /offers` then accept/decline/expire it, then | BR-OFFERS-009 | A SETTLED (declined, cancelled, or expired) prior offer from buyer B on listing L | buyer B | Submit a new offer on L | `201` — settled offers don't count against the one-open-offer rule | [CODE] |
| TS-OFFERS-005 | `PATCH /offers/:id/counter` | BR-OFFERS-006 | An offer where this party has already countered 3 times | that party | Submit a 4th counter | `400` — cap reached; Accept/Decline remain available on the same offer | [CODE] |
| TS-OFFERS-006 | `PATCH /offers/:id/accept` | BR-OFFERS-005 | An offer whose last history entry was written by the buyer (seller's turn) | the BUYER (wrong turn) | Attempt to accept | Rejected — not this party's turn (`assertRespondable`) | [CODE] |
| TS-OFFERS-007 | `PATCH /offers/:id/cancel` | BR-OFFERS-007 | An offer where it is currently the BUYER's turn to respond (not their own last move) | the buyer | Cancel anyway | `200` success — cancel is the one action deliberately exempt from the turn check | [CODE] |
| TS-OFFERS-008 | Two concurrent `PATCH /offers/:id/accept` calls on two different offers for the same single-unit listing | BR-OFFERS-011 | Two open offers (A, B) on one listing | seller, two near-simultaneous accept calls (one per offer) | Exactly one succeeds; the loser's own just-captured hold is refunded, its just-created Order is cancelled, and the buyer is notified — same `ConflictException` message whether caught by the application check or the DB partial unique index | [CODE+FIXDOC] — this is the historical `BRI-280` incident's regression test |
| TS-OFFERS-009 | `PATCH /offers/:id/accept` with a failing capture | BR-OFFERS-022 | An offer whose card will decline at capture time (Stripe test card) | seller | Accept | Immediate `400`, offer status UNCHANGED (not retried, not auto-cancelled) — **[CODE≠TICKET]**: the client's confirmed resolution (15-min retry then clean-cancel) is `BRI-297`, still not implemented | conflict/gap |
| TS-OFFERS-010 | `DELETE /me/payment-methods/:id` | BR-PAYMENT-METHODS-005 | A card backing an open offer's hold | the buyer who owns both | Attempt to delete the card | `409` — blocked before any Stripe call | [CODE] |
| TS-OFFERS-011 | `POST /offers/wallet-hold-intent` then abandon (never call `POST /offers`) | BR-OFFERS-012 area (offers.md "BRI-588") | — | buyer | Authorize a wallet hold, then close the app | **[GAP]**: no `Offer` row is created, so the hold's ONLY release mechanism is Stripe's own ~7-day authorization expiry — no immediate release exists | gap-confirmed-by-linear (BRI-588) |
| TS-OFFERS-012 | `PATCH /offers/:id/counter` on a wallet-originated offer | BR-OFFERS-020 | An offer created via the wallet path | either party | Attempt to counter | Rejected outright — wallet holds cannot be re-priced; decline+re-offer is the only path | [CODE] |
| TS-OFFERS-013 | `GET /offers` after 24h+ with no read | BR-OFFERS-021 | An offer past its `expiresAt`, never read by either party | either party | Call `GET /offers` for the first time since expiry | The stale offer is settled (hold released, status updated) as a side effect of THIS read — verify it was NOT settled before this call (e.g. was still shown live by a different read path, if one exists) | [CODE] |

## Orders & Checkout

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-ORDERS-001 | `POST /orders` | BR-ORDERS-003 | A cart with listings from 2 different sellers | buyer | Checkout | `400` before any Stripe call | [CODE] |
| TS-ORDERS-002 | `POST /orders` | BR-ORDERS-006 | A listing whose price changed after the buyer's cart was built | buyer, `expectedPriceCents` = the stale price | Checkout | `409` | [CODE] |
| TS-ORDERS-003 | Two near-simultaneous `POST /orders` for the identical cart (double-tap) | BR-ORDERS-005 | — | buyer, two requests within the same 10-second idempotency bucket | Both resolve to the SAME Order/PaymentIntent — no duplicate charge, no duplicate Order row (P2002 recovery returns the winner's order to the loser) | [CODE+FIXDOC] — regression test for the real QA-found bug behind `2026-09-06-add-order-payment-intent-unique.sql` |
| TS-ORDERS-004 | Same as TS-ORDERS-003 but minutes apart (bucket rolled over) | BR-ORDERS-005 | — | buyer, two requests 11+ seconds apart | TWO separate, genuinely distinct orders/charges — confirms the idempotency window doesn't over-suppress a real repeat purchase | [CODE] |
| TS-ORDERS-005 | `POST /orders/:id/confirm-receipt` | BR-ORDERS-013 | An order with an open (non-terminal) dispute | buyer | Attempt to confirm receipt | Rejected — blocked while a dispute is active | [CODE] |
| TS-ORDERS-006 | `POST /orders/:id/cancel` | BR-ORDERS-011 | A placed order | seller, `reason: 'damaged'` | Cancel | Listing is NOT paused (stays sellable) — contrast `reason: 'item_unavailable'`, which DOES pause it | [CODE] |
| TS-ORDERS-007 | `POST /orders/:id/request-cancellation` | BR-ORDERS-012 | A placed order | buyer, calling the ENDPOINT DIRECTLY (not through the mobile app, which has this UI commented out) | `200` success — confirms the server path is fully live despite the client hiding it | [CODE+ticket(done)] |
| TS-ORDERS-008 | `GET /seller/orders?status=bogus-value` | BR-ORDERS-019 | — | seller | Query with an invalid status string | `200` with an EMPTY result set, not a `400` — the param is unvalidated | gap-confirmed-by-code |
| TS-ORDERS-009 | `PATCH /orders/:id/status` | BR-ORDERS-001 | An order at `placed` | seller | Attempt to set `status: 'delivered'` directly (skipping intermediate states) | `400` — `ALLOWED_TRANSITIONS` is a strict forward-only DAG, no skip-ahead | [CODE] |
| TS-ORDERS-010 | `PATCH /orders/:id/status` | BR-ORDERS-001 | An order at `cancelled` | seller | Attempt ANY further transition | `400` — terminal state | [CODE] |

## Disputes

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-DISPUTES-001 | `POST /orders/:id/dispute` | BR-DISPUTES-002 | An order delivered 4+ days ago | buyer | Open a dispute | Rejected — past the 3-day report window | [CODE] |
| TS-DISPUTES-002 | `POST /orders/:id/dispute` twice | BR-DISPUTES-002 | An existing dispute on the order | buyer | Open a second dispute on the same order | Rejected — `Dispute.orderId` is `@unique` | [CODE] |
| TS-DISPUTES-003 | `POST /orders/:id/confirm-receipt` then `POST /orders/:id/dispute` | BR-DISPUTES-014 | A delivered order | buyer, confirm receipt FIRST, then attempt to open a dispute within the remaining window | **[CODE≠TICKET]**: succeeds per current code (no block) — `BRI-593` wants this blocked, not implemented | conflict/gap |
| TS-DISPUTES-004 | `PATCH /orders/:id/dispute/evidence` | BR-DISPUTES-004 | A dispute already in `awaiting_decision` | buyer | Attempt to add evidence | Rejected — the window-status gate only allows this during `seller_evidence_window` | [CODE+ticket(open: BRI-141 still open in tracker, fix present)] |
| TS-DISPUTES-005 | `PATCH /sellers/me/orders/:id/dispute/evidence` | BR-DISPUTES-005 | A dispute 48h past the 24h evidence deadline, admin has NOT yet decided | seller | Submit evidence anyway | `200` success, flips to `awaiting_decision` — no deadline enforcement on this specific action beyond `!decidedAt` | [CODE] |
| TS-DISPUTES-006 | Admin approve + seller accept-return racing | BR-DISPUTES-007 | A dispute in `awaiting_decision` | admin approve AND seller accept-return fired near-simultaneously | Exactly one succeeds (atomic `claimUndecided`); the loser gets a clean rejection, not a double label purchase | [CODE] — regression test for the `BRI-414` code-review finding |
| TS-DISPUTES-007 | `POST /orders/:id/dispute/ship` | BR-DISPUTES-010 | A dispute in `approved` status, no real carrier tracking exists (the common/only real-world case) | buyer | Tap "I've shipped it" | Refund fires IMMEDIATELY, no carrier verification — **[CODE≠TICKET]**, `BRI-594` wants carrier-scan-gated refund, not implemented | conflict/gap |
| TS-DISPUTES-008 | Dispute reaches `refund_failed` | BR-DISPUTES-012 | A dispute where the seller's connected account can't absorb the reversal (needs a specific Stripe test-mode setup) | — | Trigger the refund path | Dispute lands in `refund_failed`, admins notified; **[GAP]** no endpoint/sweep anywhere transitions it further — confirm this is a genuine dead end, not merely untested | gap-confirmed-by-code |
| TS-DISPUTES-009 | `GET /admin/dispute-cases` with a known `approved`-but-unshipped case in the DB | BR-DISPUTES-017 | A dispute stuck in `approved` for 5+ days, buyer never shipped | admin | List the queue | The stuck case is ABSENT from the list (deliberately excludes `approved`) — only reachable via `GET /admin/dispute-cases/:id` with the known order id | [CODE] |

## Listings & Inventory

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-LISTINGS-001 | `POST /listings/:id/relist` | BR-LISTINGS-005 | A LIVE (`active`) listing, not sold | seller | Relist it | `201`, a NEW listing created, the ORIGINAL remains `active` and unchanged — confirms the item is now listed twice simultaneously, a confirmed-open `BRI-673` gap | gap-confirmed-by-linear |
| TS-LISTINGS-002 | `PATCH /listings/:id/status` with `{status: 'approved'}` | BR-LISTINGS-006 | A `pending_approval` listing, caller is the SELLER (not an admin) | seller | Call this endpoint directly (not `/approve`) | **[GAP]**: succeeds, self-approving the listing — bypasses the admin-only `/approve` route's role guard entirely. High-value security test. | gap-confirmed-by-code |
| TS-LISTINGS-003 | `PATCH /listings/:id` | BR-LISTINGS-007 | A `sold` listing | seller | Attempt any edit | `409 'A sold listing cannot be edited'` | [CODE] |
| TS-LISTINGS-004 | `PATCH /listings/:id` crossing the high-value threshold | BR-LISTINGS-008 | A live `approved` listing at $1900 | seller, edit price to $2100 | Save | Listing demotes to `pending_approval`, open offers cancelled | [CODE] |
| TS-LISTINGS-005 | `GET /listings/:id/likes` vs `GET /listings/:id/comments` on an unknown id | BR-LISTINGS-022 | — | anon | Call both for a nonexistent listing id | likes → `404`; comments → `200` with `[]` — confirms the documented inconsistency between the two | gap-confirmed-by-code |
| TS-LISTINGS-006 | Rapid like→unlike→like | BR-LISTINGS-024 | A likeable listing | one buyer, 3 rapid direct API calls (bypassing the mobile client's `pendingSync` protection) | **[GAP]**: no server-side serialization — final state is not guaranteed to match the last call issued | gap-confirmed-by-code |
| TS-LISTINGS-007 | `POST /listings/:id/comments` on a `pending_approval` listing | BR-LISTINGS-025 | A `pending_approval` listing (not visible via `GET /:id` to a non-owner) | a buyer who somehow has the listing id | Post a comment | **[GAP]**: succeeds — no status gate, unlike `likeListing`'s `NON_LIKEABLE_LISTING_STATUSES` check | gap-confirmed-by-code |
| TS-INVENTORY-001 | `PUT /seller/inventory/listings/:listingId` with `quantityAvailable: -5` | BR-INVENTORY-005 | — | seller | Submit a negative quantity | `200` with `onHand` recomputed as if `0` was sent — NOT a `400`, despite the DTO's own `@Min(0)` decorator appearing to promise one | gap-confirmed-by-code |
| TS-INVENTORY-002 | `GET /seller/inventory/listings/:listingId` on a soft-deleted listing | BR-INVENTORY-003 | A listing the seller soft-deleted (via `DELETE /listings/:id`) | seller | Read its inventory via this endpoint | `200` — succeeds despite the listing being invisible everywhere else (no soft-delete filter on this ownership check) | gap-confirmed-by-code |
| TS-INVENTORY-003 | `GET /seller/inventory` with a `sold`-but-`available>0` drift row present | BR-INVENTORY-004 | A listing manually put into this drift state | seller | List inventory | The row is flipped back to `active` as a SIDE EFFECT of this GET — verify the listing's own status changed, not just the response value | [CODE+TEST] |

## Messaging

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-MESSAGING-001 | `POST /conversations/:id/messages` | BR-MESSAGING-008 | A conversation | either party, body containing an off-platform-payment phrase (e.g. "send me cash via Venmo") | `403 OFF_PLATFORM_PAYMENT`, message NEVER persisted | [CODE] |
| TS-MESSAGING-002 | Same endpoint | BR-MESSAGING-008 | — | either party, mild profanity | Message IS persisted and delivered, `isFlagged: true` | [CODE] |
| TS-MESSAGING-003 | `POST /conversations/:id/messages` from a non-participant | — | A conversation between A and B | account C (not a party) | Attempt to send | `403`, no admin bypass on this specific route (contrast `GET /conversations/:id`) | [CODE] |
| TS-MESSAGING-004 | `GET /conversations/:id` from an ADMIN who is not a participant | BR-MESSAGING-005 | — | an admin account | Read a conversation they're not part of | `200` success — the one admin-bypass route in the buyer/seller controller | [CODE] |
| TS-MESSAGING-005 | `POST /conversations/:id/block` | BR-MESSAGING-014 | A conversation with an open offer between the two parties | either party | Block the other | The open offer is silently cancelled — buyer gets NO notification about this specific side effect | [CODE] |
| TS-MESSAGING-006 | `POST /conversations` between an already-blocked pair | BR-MESSAGING-003 | A->B block in place | A | Create a new conversation targeting B | **[GAP]**: succeeds — no block check at creation time at all | gap-confirmed-by-code |
| TS-MESSAGING-007 | `POST /admin/conversation-reports/:id/resolve` with `action: 'warn', lockConversation: true` | BR-MESSAGING-021 | An open report | admin | Resolve with warn + lockConversation | Warning applied; conversation NOT locked — `lockConversation` is silently ignored for anything but `ban` | gap-confirmed-by-linear (BRI-562) |
| TS-MESSAGING-008 | `chatWarningCount` reaching 3 | BR-MESSAGING-021 | A user with 2 prior warnings | admin issues a 3rd warn | Resolve | Auto-escalates to a 100-year ban + a second system message, beyond what the admin explicitly requested | [CODE] |

## Reviews

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-REVIEWS-001 | `POST /orders/:id/review` | BR-REVIEWS-002 | A delivered order, 10+ days old | buyer | Submit a first review | `201` success — **[CODE≠TICKET]**: `BRI-96` states a 7-day review window the code doesn't enforce at all | conflict |
| TS-REVIEWS-002 | `POST /orders/:id/review` twice, concurrently | BR-REVIEWS-004 | A delivered order, no review yet | buyer, two near-simultaneous submissions | One succeeds normally; the race case produces `409 'You have already reviewed this order.'` via the P2002 catch — never a raw 500 | [CODE+FIXDOC] — regression test for `BRI-785`/`BRI-831` |
| TS-REVIEWS-003 | `POST /orders/:id/review` resubmission (not concurrent) | BR-REVIEWS-004 | An order already reviewed, within the 30-day window | buyer, submit again with different content | `201` — silently OVERWRITES the existing review, no "already reviewed" error on the sequential (non-race) path | [CODE] |
| TS-REVIEWS-004 | `PATCH /orders/:id/review` | BR-REVIEWS-005 | A review 31+ days old | the reviewer | Attempt to edit | `403`, "30-day window has passed" | [CODE] |
| TS-REVIEWS-005 | `DELETE /sellers/me/seller-reviews/:id` | BR-REVIEWS-009 | A genuine, accurate, unflagged 1-star review of the seller's own shop | that seller | Delete it | `200` success — **[GAP]**: no restriction on which reviews a seller may delete | gap-confirmed-by-linear (BRI-566) |
| TS-REVIEWS-006 | `POST /sellers/me/seller-reviews/:id/reply` end-to-end | BR-REVIEWS-010 | A seller review | that seller | Reply, then check both mobile and web for a way to VIEW the reply | API succeeds; **neither app has any UI to display or compose a reply** — confirm via a UI walkthrough, not an API call alone | gap-confirmed-by-linear (BRI-98 "DO NOT BUILD") |
| TS-REVIEWS-007 | `GET /listings/:id/reviews` for a listing with real `ProductReview` rows (seeded directly, not via the live composer) | BR-REVIEWS-007/008 | Seed data with `ProductReview` rows (since the live mobile composer never creates them) | anon | Fetch | Correctly returns and aggregates the seeded rows — confirms the endpoint itself works; the gap is upstream (no real-world data ever reaches it) | [CODE] |

## Sellers, Connect & Payouts

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-SELLERS-001 | `GET /sellers/check-shop-name` | BR-SELLERS-002 | A seller whose current shop name is "Cowgirl Kate" | that same seller | Check availability of "Cowgirl Kate" (their own current name) | `{ available: false, reason: 'taken' }` — **[GAP]**: reports their own name as taken since `excludeUserId` isn't passed on this route | gap-confirmed-by-linear (BRI-605) |
| TS-SELLERS-002 | `POST /sellers/apply` | BR-SELLERS-004 | Phone verified 35 minutes ago (past the 30-min TTL) | seller applicant | Submit the application | Rejected — "Please verify your mobile number before continuing," even though verification technically succeeded earlier in the session | [CODE] |
| TS-SELLERS-003 | `POST /sellers/apply` with a deliverable-per-format-but-Shippo-flagged address | BR-SELLERS-004 | A real street address Shippo's API actively reports as undeliverable | seller applicant | Submit | `400` with Shippo's own message — hard block | [CODE] |
| TS-SELLERS-004 | Same as above but Shippo is unreachable (simulate a timeout/misconfigured token) | BR-SELLERS-004 | — | seller applicant | Submit the identical request | `201` success — fails OPEN on a Shippo outage, contrast TS-SELLERS-003's hard block | [CODE] — the two scenarios together prove the fail-open/fail-closed distinction is real and intentional |
| TS-SELLERS-005 | `PATCH /sellers/me/orders/:id/ship` auto-purchase path, missing package dimensions | BR-SELLERS-012 | An order with items lacking package dimensions | seller | Ship with no `trackingNumber` in the body | Falls back silently to whatever was in the body (none) rather than erroring — confirms "missing precondition" is NOT treated as a failure | [CODE] |
| TS-SELLERS-006 | Same endpoint, genuine Shippo API failure during auto-purchase attempt | BR-SELLERS-012 | All preconditions met, Shippo simulated as down | seller | Ship | `503`, admins notified — contrast TS-SELLERS-005: a genuine failure is NOT a silent fallback | [CODE] |
| TS-SELLERS-007 | `POST /sellers/me/orders/:id/shipping-label` with a `rateId` quoted for a DIFFERENT order | BR-SELLERS-015 | Two open orders A and B, a shipping-rate quote obtained for A | seller | Attempt to purchase A's quoted rate against order B | `400 'This rate was not quoted for this order'` | [CODE] — high-value correctness/security test |
| TS-CONNECT-001 | `POST /sellers/connect/onboard` twice | BR-CONNECT-001 | — | the same seller | Call onboard a second time | Returns the SAME `stripeAccountId`, no second Stripe account created | [CODE] |
| TS-CONNECT-002 | `GET /sellers/connect/status` with `force=true` immediately after completing Stripe verification in the embedded onboarding flow | BR-CONNECT-006 | A seller who just finished Stripe verification | that seller | Call with `?force=true` | `payoutsEnabled: true` reflected immediately, bypassing the normal 1-hour staleness window — **[CODE≠TICKET]**: `REDB1-48`/`BRI-786` is Reopened, meaning this may be regressed for some real-world path not yet isolated | conflict — prioritize a real device test here |
| TS-CONNECT-003 | `POST /sellers/connect/account-session/payout` | BR-CONNECT-008 | Phone verified 6 minutes ago (past the 5-min payout-specific TTL, though within the 30-min general TTL) | seller | Request a payout-account session | `403 PAYOUT_2FA_NOT_VERIFIED` — confirms the tighter 5-minute window is actually enforced, distinct from the 30-minute one `apply()` uses | [CODE] |
| TS-CONNECT-004 | `refundOrder` on an order with an open `StripeDispute` | BR-DISPUTES-013 | An order with a real, open Stripe chargeback | admin or dispute-flow trigger | Attempt any refund path | `400` — blocked entirely while the chargeback is open | [CODE] |

## Admin

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-ADMIN-001 | `PATCH /admin/users/:id/role` | BR-ADMIN-004 | A regular `USER` account | an existing admin | Set `role: ADMIN` on the target | `200` success, no additional confirmation required — **highest-priority privilege-escalation test in this knowledge base**; confirm whether any audit trail is written anywhere (not found in this analysis) | gap-confirmed-by-code |
| TS-ADMIN-002 | `DELETE /admin/taxonomy/categories/:id` vs `DELETE /admin/taxonomy/subcategories/:id` | BR-ADMIN-003 | A category with live listings vs. a subcategory with live listings | admin | Attempt to delete each | Category delete → `409` (blocked); Subcategory delete → succeeds, cascading to its types with NO reference check — confirm this asymmetry is reproducible, then flag for a product decision | gap-confirmed-by-code |
| TS-ADMIN-003 | `DELETE /admin/taxonomy/brands/:id` on a brand with live listings | BR-ADMIN-007 | — | admin | Delete | `409` — this guard is LOAD-BEARING (unlike category's, which a DB constraint might also catch) since `Listing.brandId` is nullable at the DB level | [CODE] |
| TS-ADMIN-004 | `PUT /admin/taxonomy/materials/order` with a stale id list | BR-ADMIN-006 | A material added by a second admin in another tab after this admin loaded the list | admin, submit a reorder missing the new material's id | `409 'The materials list changed since you loaded it. Reload and try again.'` — never partially applied | [CODE] |
| TS-ADMIN-005 | `GET /admin/authenticity` boundary | BR-ADMIN-005 | Two listings: one at $99.99 `active`, one at $100.00 `active` | admin | List the authenticity queue | Only the $100.00 listing appears, confirming the exact price boundary | [CODE] |
| TS-ADMIN-006 | `POST /admin/payouts/:orderId/retry-reversal` on a payout NOT in `reversal_failed` | — | A normal `transferred` payout | admin | Attempt to retry | `400 "nothing to retry"` | [CODE] |

## Uploads & AI

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-UPLOADS-001 | `POST /uploads/listings` with a `.exe` renamed to `.jpg` | BR-UPLOADS-004 | — | seller | Upload the disguised file | Rejected — magic-byte content sniffing, not the client-declared extension/mimetype | [CODE] |
| TS-UPLOADS-002 | `POST /uploads/listings` with 0 files | BR-UPLOADS-005 | — | seller | Submit the multipart request with an empty `files` field | `400 'No files provided'` | [CODE] |
| TS-UPLOADS-003 | `POST /uploads/reviews` with 0 files | BR-UPLOADS-005 | — | any authenticated user | Submit with an empty `files` field | `200 { urls: [] }` — NOT a 400, contrasting TS-UPLOADS-002 | [CODE] |
| TS-UPLOADS-004 | `GET /uploads/evidence/:filename` with a guessed/incorrect filename | BR-UPLOADS-003 | — | anon or any authenticated user | Request a plausible-looking but wrong filename | `404` (the presigned-URL generation fails cleanly) — confirms there's no enumeration path, while also confirming there's no IDENTITY check either (a correct filename from any source succeeds for anyone) | [CODE] |
| TS-UPLOADS-005 | `POST /uploads/listing-video` over 50MB | — | — | seller | Upload an oversized video | `413`, aborted mid-stream (not buffered fully first) | [CODE] |
| TS-AI-001 | `POST /ai/analyze` as a non-seller | BR-AI-001 | A regular buyer account | that buyer | Call the endpoint | `403` — role-gated, not merely auth-gated | [CODE] |
| TS-AI-002 | `GET /ai/price-comps` with only `categoryId` | BR-AI-002 | — | seller | Query with one of three required tiers | `200` with the "not enough data" empty shape — never a `400` | [CODE] |
| TS-AI-003 | `POST /ai/regenerate` direct API call | BR-AI-003 | — | seller | Call directly (bypassing the mobile app, which has no UI for this) | `200` success, identical behavior to `/ai/analyze` — confirms the endpoint is live even though unreachable through the shipped app | [CODE] |

## Seed & Embeddings (data-safety-focused)

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-SEED-001 | `POST /seed/run` twice in a row | BR-SEED-001 | A fresh non-production environment | anon (no auth required) | Call it twice | Second call does not duplicate or error — every step is upsert-based | [CODE] |
| TS-SEED-002 | `POST /seed/run` against a database with real, unrelated pre-existing data | BR-SEED-001 | A non-production environment with real test-user accounts already present | anon | Call it | Existing unrelated rows are untouched; only the seed's own natural-key rows (by slug/email/code) are inserted or no-op'd | [CODE] — **do not actually run this against any shared/real database per this task's own hard database-safety rule; this scenario should be exercised only against a disposable local/CI database** |
| TS-SEED-003 | `POST /seed/run` with `NODE_ENV=production` | BR-SEED-002 | — | anon | Call it | `404`, indistinguishable from a nonexistent route | [CODE] |
| TS-EMBEDDINGS-001 | `POST /embeddings/reconcile` | BR-EMBEDDINGS-002 | — | anon (non-prod) | Call it | `200 { queued: true, jobId }` immediately — this does NOT confirm the reconciliation itself completed; a separate worker-side check is needed to verify the actual effect | [CODE] |

---

## Cross-cutting scenario: idempotency corrections

| ID | Endpoint/Flow | Rule(s) | Setup | Actor | Action | Expected | Source |
|---|---|---|---|---|---|---|---|
| TS-IDEMPOTENCY-001 | `POST /orders` double-tap within 10s | BR-IDEMPOTENCY-GLOBAL-001 | — | buyer | Double-tap checkout | Exactly one PaymentIntent, one Order (Stripe-operation idempotency — CLOSED, tested) | [CODE+TEST] |
| TS-IDEMPOTENCY-002 | `POST /listings/:id/comments` double-tap | BR-IDEMPOTENCY-GLOBAL-001 | A listing | any authenticated user | Rapid double-submit the identical comment text | **[GAP]**: two comment rows are created — no idempotency protection exists for this endpoint (or most others outside the specifically-hardened checkout/offer-hold/Connect-transfer paths) | gap-confirmed-by-code — representative of the general case; repeat this shape for any other mutating endpoint a test plan wants to specifically harden |

---

## Endpoints explicitly NOT scenario'd in this pass (and why)

- **Pure static-content reads with no auth, no params, no state** (`GET /health`, `GET /shipping/tiers`, `GET /brands`, `GET /materials`, `GET /categories`): a single "200 with the expected static shape" scenario per endpoint is sufficient and was already effectively specified in each `modules/<name>.md`'s own endpoint section — repeating a one-line scenario 10+ times here adds no value.
- **The 42 fully-`analyzed` `admin` endpoints not listed above**: most are standard paginated list/CRUD reads with no business-rule-driven edge case beyond "admin role required" (already covered once in `dependency-map.json`'s `genericPatterns`). The ones with genuine risk (money-moving, destructive, privilege-related) are all scenario'd above.
- **The 14 `partial`-status endpoints in `endpoint-inventory.json`** (`feed`'s 6 ranking-algorithm endpoints + 8 lighter-pass `admin` list reads): deliberately not scenario'd with the same confidence as `analyzed` endpoints, since their underlying business logic wasn't independently re-traced to the same depth — a future pass completing those endpoints' analysis should derive their scenarios then, not before.
