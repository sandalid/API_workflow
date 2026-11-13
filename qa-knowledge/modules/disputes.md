# Module: disputes

**Scope**: `apps/api/src/disputes/` — controller, service, repository, DTOs. 11 HTTP endpoints (buyer: 5, seller: 2, admin: 4).

Source files traced in full:
- `apps/api/src/disputes/disputes.controller.ts`
- `apps/api/src/disputes/disputes.service.ts` (798 lines, full read)
- `apps/api/src/disputes/disputes.repository.ts`
- `apps/api/src/disputes/dto/*.ts` (all 3 DTOs)
- `apps/api/prisma/schema.prisma`: `Dispute` (`:1348-1376`), `StripeDispute` (`:1385-1424`), `enum DisputeStatus` (`:195-207`), `enum DisputeReason` (`:186-193`)
- Cross-module reads for context only (not re-analyzed as their own module): `ConnectService.refundOrder`/`reverseTransferIfNeeded` (`connect.service.ts:1208-1322`), `ShippoService`/`shippo-status.mapping.ts`

## Two distinct "dispute" concepts — do not conflate

1. **`Dispute` model** (this module) — a buyer-initiated return/quality claim against the seller, arbitrated by Redspur. One row per order (`@unique orderId`, `schema.prisma:1350`). This is "Flow B" / the Returns & Disputes epic (Linear **BRI-63**).
2. **`StripeDispute` model** (admin module's territory — `admin.controller.ts`'s `/admin/stripe-chargebacks*`, NOT in this batch) — a genuine Stripe chargeback the buyer filed with their bank (`charge.dispute.created` webhook). Carries its own `status` string mirroring Stripe's own vocabulary (`needs_response|won|lost|warning_closed`...) and its own `evidenceDueBy` (Stripe's `evidence_details.due_by` — this is the field the task's manual-sql evidence `2026-09-05-add-stripe-dispute-evidence-due-by.sql` adds; it belongs to `StripeDispute`, **not** `Dispute` — the internal claim's analogous deadline is `Dispute.sellerEvidenceDeadline`, a different column entirely).

**An order can carry both simultaneously** — a buyer claim Redspur is arbitrating, and separately a chargeback the buyer filed with their bank (code comment, `schema.prisma:1380-1382`). `ConnectService.refundOrder` (called from this module's `triggerReturnRefund` and from `OrdersService.finalizeCancellation`) blocks on an **open `StripeDispute`**, deliberately NOT on `Dispute.payoutHeld` — because `Dispute`'s own refund flow (`markReturnShipped`) sets `payoutHeld` true on itself while its refund is in flight, and gating on that boolean would block the exact call meant to resolve it (`connect.service.ts:1209-1213`, `ConnectRepository.findOpenStripeDisputeByOrderId`).

`OrderDetail.tsx` surfaces both independently: the internal claim via `isActiveDispute(dispute)` → "Dispute in progress" card (`:586-601`), and the Stripe chargeback via `order.stripeDisputeStatus` → "Payment disputed" card (`:603-619`) — these can both render on the same order simultaneously, which is correct per the schema's own stated intent.

## Dispute state machine

`enum DisputeStatus` (`schema.prisma:195-207`): `seller_evidence_window (default) | awaiting_decision | approved | denied | withdrawn | refunded | refund_failed`.

Terminal per both server (`TERMINAL_DISPUTE_STATUSES`, `orders.service.ts:72`, used for `hasActiveDispute`) and mobile (`TERMINAL_DISPUTE_STATUSES`, `apps/mobile/src/utils/disputeStatus.ts:5`): **`denied | withdrawn | refunded`** — both copies agree exactly, including the subtlety that `approved` is **not** terminal (claim upheld, refund not yet settled, payout must stay held) and, notably, **`refund_failed` is not terminal either** in either copy. See Gaps for why that matters on the mobile UI.

```
seller_evidence_window --(24h lapses, no response, lazy-on-read)--> awaiting_decision
seller_evidence_window --(seller submits evidence)-----------------> awaiting_decision
seller_evidence_window --(seller "accept return" shortcut)---------> approved (sellerAcceptedReturn=true)
seller_evidence_window --(buyer withdraws)--------------------------> withdrawn
awaiting_decision      --(buyer withdraws)--------------------------> withdrawn
awaiting_decision      --(admin approve)----------------------------> approved
awaiting_decision      --(admin deny)--------------------------------> denied
approved               --(carrier scan OR buyer "I've shipped it" tap, refund succeeds)--> refunded
approved               --(refund attempt throws)------------------------------------------> refund_failed
```

No transition is defined OUT of `denied`/`withdrawn`/`refunded`/`refund_failed` anywhere in the service — all four are dead ends in the code as read (`refund_failed` has no retry entry point found; see Gaps).

## Who can act at each stage

| Action | Endpoint | Actor | Gate |
|---|---|---|---|
| Open dispute | `POST /orders/:id/dispute` | Buyer (order owner) | `order.status === 'delivered'`, within 3 days of `deliveredAt`, no existing dispute for the order |
| Read dispute | `GET /orders/:id/dispute` | Buyer or seller (order parties) | — |
| Add evidence | `PATCH /orders/:id/dispute/evidence` | Buyer (order owner) | `!decidedAt` AND `status === 'seller_evidence_window'` (BRI-141 fix) |
| Withdraw | `POST /orders/:id/dispute/withdraw` | Buyer (order owner) | `!decidedAt` (i.e. not yet `approved`/`denied`) |
| Mark shipped | `POST /orders/:id/dispute/ship` | Buyer (order owner) | `status === 'approved'` |
| Submit evidence | `PATCH /sellers/me/orders/:id/dispute/evidence` | Seller (order owner) | `!decidedAt` (no window-status check — seller can submit **after** the 24h deadline nominally lapsed, as long as admin hasn't decided yet) |
| Accept return | `PATCH /sellers/me/orders/:id/dispute/accept-return` | Seller (order owner) | `!decidedAt` |
| List cases | `GET /admin/dispute-cases` | Admin | Only `seller_evidence_window`/`awaiting_decision` statuses returned |
| Get one case | `GET /admin/dispute-cases/:id` | Admin | Any status, by id |
| Approve | `POST /admin/dispute-cases/:id/approve` | Admin | `!decidedAt`, atomic claim |
| Deny | `POST /admin/dispute-cases/:id/deny` | Admin | `!decidedAt`, atomic claim |

Buyer/seller ownership checks: `getOwned(orderId, userId, side)` (`disputes.service.ts:705-711`) resolves `buyerId`/`sellerId` off the **order**, not the dispute — a 403 for anyone who isn't that order's buyer/seller, a 404 if no dispute row exists for the order at all.

## Report window and evidence window — verified exact math

- **Report window**: `REPORT_WINDOW_MS = 3 days` (`:32`) from `order.deliveredAt ?? order.updatedAt` (fallback only for pre-`deliveredAt`-column orders) — mirrors the mobile "Delivered · 3-day window" screen's own gate, enforced server-side too so a stale client build can't file outside it (`reportDispute`, `:66-82`).
- **Seller evidence window**: `EVIDENCE_WINDOW_MS = 24h` (`:28`), set as `Dispute.sellerEvidenceDeadline` at creation (`:91`). Lapsing is **lazy-on-read** (`maybeAdvanceEvidenceWindow`, `:136-141`) — checked on `getByOrderId`, `getCaseForAdmin`, and every row in `listOpenCasesForAdmin`. No cron.
- **Return-ship window**: `SHIP_WINDOW_MS = 5 business days per copy, 5 calendar days in code` (`:40`) — after `approveInternal` sets `decidedAt`, if the buyer never ships, `maybeAutoReleasePayoutHold` (`:156-168`, lazy-on-read, checked on `getByOrderId`/`getCaseForAdmin` only) releases `Order.payoutHeld` back to `false` **without resolving the dispute** (`status` stays `approved` forever until a late ship eventually refunds it). This only fires for a case someone actually reads via those two entry points — `listOpenCasesForAdmin`/`findOpenForAdmin` **excludes `approved`** from the admin queue (`disputes.repository.ts:163`), so a stuck approved-but-unshipped case is invisible on the admin list and only surfaces via a direct by-id lookup (support investigating a specific order) — documented explicitly in the code's own comment (`:477-480`) as a known limitation, not accidental.

## Evidence/accept-return/refund flow in detail

- **`reportDispute`** (`:66-103`): creates the `Dispute` row, sets `Order.payoutHeld = true` immediately (before any seller response), notifies the seller. **No check against `Order.receiptConfirmedAt`** — only `order.status === 'delivered'` and the 3-day window are checked. Since `confirmReceipt` does **not** change `order.status` away from `'delivered'` (it only sets `receiptConfirmedAt`/`receiptAutoConfirmed`), a buyer who has already confirmed receipt can still open a dispute within the same 3-day window. This is a live gap — see `gaps.md` (BRI-593 documents exactly this as "Required Behaviour: block opening a claim after confirm").
- **`addBuyerEvidence`** (`:170-184`): appends to `buyerDescription`/`buyerEvidencePhotos`, does not change status. Blocked once status leaves `seller_evidence_window` (BRI-141 — Linear ticket is `Backlog`/open but the **code already has the fix**; worth a regression-style test, not a "this is broken" assumption).
- **`withdrawDispute`** (`:186-200`): releases `Order.payoutHeld` immediately, notifies seller ("Your payout is no longer on hold").
- **`submitSellerEvidence`** (`:202-219`): appends evidence, stamps `sellerRespondedAt`, and **unconditionally** flips status to `awaiting_decision` — even if called a second before the 24h window would have lapsed anyway, or (per the ownership check only, no window-status gate) well after it. Notifies the buyer.
- **`sellerAcceptReturn`** (`:221-226` → `approveInternal(…, sellerAccepted=true)`): the RS1 shortcut — seller concedes immediately, skipping admin review entirely. Same internal code path as an admin approval.
- **`approveInternal`** (`:520-563`): atomic `claimUndecided` (prevents a seller-accepts/admin-approves race or a double-click both buying a real paid Shippo label for the same dispute — BRI-414 code-review finding #2), then `purchaseReturnLabel` (real Shippo label, ship buyer→seller reversed from the outbound leg, $300+ Xcover insurance mirroring the outbound leg). **Falls back to a mock label URL only when the purchase was never attempted** (missing package dimensions / missing shipping address / no seller profile / parcel over the 50lb/108in cap) — a **genuine Shippo failure now throws `ServiceUnavailableException`** instead of silently faking a label (BRI-414 fix). Linear **BRI-657** ("Seller cannot accept a return — generic 'contact Redspur administration' error") matches this exact code path: a live Shippo failure during `sellerAcceptReturn` surfaces as a 503 with no retry affordance in the mobile UI, which is accurate to the code (the `ServiceUnavailableException` propagates straight to the client) but the Linear ticket (status `Backlog`) treats the 503 itself as the bug, i.e. the UX around it needs a retry path, not that the guard is wrong.
- **`markReturnShipped`** (`:238-248`) / **`maybeAdvanceReturnFromCarrierTracking`+`applyReturnTrackingStatus`** (`:342-401`) both converge on **`triggerReturnRefund`** (`:266-326`), the single refund trigger, atomically claimed via `claimReturnShipped` (`returnShippedAt` CAS — BRI-414 code-review finding #5, prevents a carrier-scan poll racing a webhook racing the buyer's own tap from double-refunding). **The buyer's own "I've shipped it" tap still refunds immediately, with no carrier verification, for any dispute whose return label fell back to the mock URL** (no listing has package dimensions yet per the code's own comment) — this is Linear **BRI-594**'s exact open concern ("refund on carrier scan… not when the buyer taps") and remains true today for every real-world dispute, since package dimensions are still not collected anywhere in the listing flow per this read.
- **Refund failure** (`:286-299`): `connect.refundOrder` can throw (most likely the seller's connected-account balance can't cover a transfer reversal). On failure: dispute → `refund_failed`, every admin notified (`dispute_refund_failed`), `false` returned (never throws out of `triggerReturnRefund` itself, so a carrier-scan poll doesn't need special-casing). **No retry mechanism for `refund_failed` was found anywhere in this module** — no endpoint, no lazy sweep, nothing transitions a dispute out of `refund_failed`. This matches the manual-sql evidence (`2026-09-03-add-dispute-refund-failed-states.sql`) making this a first-class queryable state rather than a log line, but the state is still a dead end once reached (see `gaps.md`).

## Admin arbitration console

- `listOpenCasesForAdmin`/`getCaseForAdmin` both run `maybeAdvanceEvidenceWindow` before serializing (so a stale-looking `seller_evidence_window` case advances to `awaiting_decision` the moment an admin looks at the queue, not only on a buyer/seller read).
- `approveCaseForAdmin`/`denyCaseForAdmin` both guard `!dispute.decidedAt` at the service layer in addition to the repository's atomic `claimUndecided`/`claimUndecided` (deny also uses the atomic claim, `:504`) — belt-and-braces against the exact race `approveInternal`'s own comment describes.
- `denyCaseForAdmin` (`:499-518`) releases `Order.payoutHeld` and notifies **only the buyer** — the seller is never notified that their payout hold was released or that they were "paid" in any of: deny, approve, or refunded. Linear **BRI-619** ("Tell the seller when a claim is approved, denied or refunded") documents this exact, still-open gap, confirmed directly against this read of `approveInternal`/`denyCaseForAdmin`/`triggerReturnRefund` — none of the three notifies `dispute.order.sellerId`.
- `computeAiFirstPass` (`:717-757`): a **deterministic heuristic, not a live AI model call** — confidence/rationale derived purely from which side submitted evidence. Documented in its own doc comment as intentionally not wired to the real `ai/` module's OpenAI integration. Test scenarios should treat its output as a pure function of dispute state, not as anything requiring a mocked LLM.

## DTO validation gaps worth testing directly

- `ReportDisputeDto.description` (`report-dispute.dto.ts:10-13`): `@IsString() @MaxLength(1000)`, **no `@IsNotEmpty()`** — an empty string `""` passes validation. `AddEvidenceDto.notes` is `@IsOptional()` so emptiness there is moot, but a dispute's *required* description field can be submitted blank.
- `GetAdminDisputeCasesQueryDto.q` (free-text search) has no `@MaxLength` — an arbitrarily long query string reaches a Prisma `contains`/`insensitive` filter across multiple joined tables (`disputes.repository.ts:161-180`).

## Endpoint-by-endpoint summary

| Endpoint | Guard | Key business rules |
|---|---|---|
| `POST /orders/:id/dispute` | JWT, buyer-owns-order | `delivered`-only, 3-day window, one dispute per order, no `receiptConfirmedAt` check (gap) |
| `GET /orders/:id/dispute` | JWT, buyer-or-seller | 404 (not null) when none exists — deliberate, documented for the mobile `apiClient`'s JSON-parse behavior |
| `PATCH /orders/:id/dispute/evidence` | JWT, buyer-owns-dispute | Only during `seller_evidence_window` |
| `POST /orders/:id/dispute/withdraw` | JWT, buyer-owns-dispute | Only while `!decidedAt` |
| `POST /orders/:id/dispute/ship` | JWT, buyer-owns-dispute | Only while `status === 'approved'`; atomic refund claim |
| `PATCH /sellers/me/orders/:id/dispute/evidence` | JWT + RolesGuard(SELLER) | Only while `!decidedAt`; always moves to `awaiting_decision` |
| `PATCH /sellers/me/orders/:id/dispute/accept-return` | JWT + RolesGuard(SELLER) | Only while `!decidedAt`; same internal path as admin approve |
| `GET /admin/dispute-cases` | JWT + RolesGuard(ADMIN) | Excludes `approved`/terminal statuses |
| `GET /admin/dispute-cases/:id` | JWT + RolesGuard(ADMIN) | Any status; only entry point that surfaces a stuck `approved` case |
| `POST /admin/dispute-cases/:id/approve` | JWT + RolesGuard(ADMIN) | Atomic claim; real Shippo label or throws |
| `POST /admin/dispute-cases/:id/deny` | JWT + RolesGuard(ADMIN) | Atomic claim; notifies buyer only |

## Web (admin portal) cross-reference

`apps/web/src/lib/api.ts` (`:453-462`) calls all four `admin/dispute-cases*` endpoints — this is the **new** arbitration console. A **separate**, older `/admin/disputes` + `/admin/orders/:id/resolve-dispute` + `/admin/orders/:id/issue-refund` surface also exists (`api.ts:424-437`, pages at `apps/web/src/app/admin/disputes/page.tsx` and `[id]/page.tsx`) — that older surface is `admin.controller.ts` territory (a separate agent's assignment per the task instructions) but it is the subject of Linear **BRI-556** ("'Cancelled & returned orders' list — is it needed") questioning whether it should still exist alongside the dispute-cases console. Flag this overlap for whoever reconciles the two modules' knowledge — don't treat it as this module's bug.

See `qa-knowledge/fragments/orders-disputes.*` for the structured business-rules/test-scenarios/dependency-map/gaps/flows/endpoint-status shared with `orders.md`.
