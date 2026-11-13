# Module: Reviews

14 endpoints, `apps/api/src/reviews/` (`reviews.controller.ts` — 172 lines, `reviews.service.ts` — 395 lines, `reviews.repository.ts` — 330 lines, `reviews.module.ts`, `dto/`). Backed by three Prisma models (`Review`, `ProductReview`, `ReviewReport`) + two enums (`ReviewTargetType`, `ReviewReportReason`, `ReviewReportStatus`) in `apps/api/prisma/schema.prisma` (lines 245–262, 1529–1615). Tests: `reviews.service.spec.ts` (809 lines), `reviews.repository.spec.ts` (117 lines), `apps/api/test/reviews.e2e-spec.ts` (opt-in, real-RDS-shaped but mocks `PrismaService` directly — still exercises the full Nest pipeline: guards, `ValidationPipe`, `AllExceptionsFilter`). No `reviews.controller.spec.ts` exists as a separate file — controller delegation is covered implicitly by the service/e2e specs.

Everything below was read from the code on `docs/qa-knowledge-base` (cut from `origin/development`, 2026-11-10) plus the cited fix write-ups and Linear tickets — nothing was executed, no API was called, no migration or seed script was run.

## Primary sources consolidated here

- Code: `apps/api/src/reviews/*.ts` (controller/service/repository/DTOs/module), `apps/api/prisma/schema.prisma` (`Review`/`ProductReview`/`ReviewReport` models, `ReviewTargetType`/`ReviewReportReason`/`ReviewReportStatus` enums), `apps/api/prisma/manual-sql/2026-10-27-fix-review-unique-order-constraint.sql`.
- Fix write-ups: `docs/fix/reviews/BRI-785.md`, `docs/fix/reviews/BRI-831.md`.
- Feature doc: `docs/features/guest-seller-reviews-page.md` (REDB1-30 — the "Seller Reviews" screen this module's data ultimately feeds, via the **users** module's `GET /users/:id/reviews`, not this module).
- Mobile: `apps/mobile/src/services/reviewsApi.ts`, `apps/mobile/src/services/sellersApi.ts` (reviews section), `apps/mobile/src/screens/profile/{RateReview,EditReview,ReviewSubmitted,OrderDetail}.tsx`, `apps/mobile/src/screens/home/AllProductReviews.tsx`, `apps/mobile/src/screens/seller/hub/{SellerHubReviews,ReportReviewSheet}.tsx`.
- Web: `apps/web/src/lib/api.ts` (`adminApi.getReviews/deleteReview/deleteProductReview`), `apps/web/src/lib/sellerApi.ts` (seller review section), `apps/web/src/app/admin/reviews/page.tsx`, `apps/web/src/app/seller/reviews/page.tsx`.
- Linear: teams `BRI` and `REDB1`, queried by keyword `review`/`rating`. `BRI-66` is the Reviews epic (scope-resolution record); `BRI-96`/`BRI-97` are the buyer-side composer/lifecycle specs; `BRI-111`/`BRI-565`/`BRI-566` are the admin-moderation specs (two still open-question/Backlog); `BRI-785`/`BRI-831` are the duplicate-review/500-error incident pair the task flagged via the manual-sql file; `BRI-98` is the cancelled seller-reply ticket; `BRI-596` is the dead-ProductReview-flow ticket; `REDB1-36` is a live, unresolved bug this analysis root-causes below.

## The two review concepts, precisely

The module models **two genuinely independent review rows**, not one review split in two:

| | `Review` | `ProductReview` |
|---|---|---|
| Rates | the seller / the transaction | one specific listing |
| Uniqueness | `@@unique([reviewerId, orderId])` — one per **order** | `@@unique([reviewerId, listingId])` — one per **listing** |
| Required | yes (`sellerRating` 1–5, mandatory on the DTO) | no (`products[]` is optional, up to 50 entries) |
| Extra fields | `itemAsDescribed`/`shippingSpeed`/`communication` (optional 1–5 sub-ratings), `replyText`/`repliedAt` (seller reply) | none of the above — just `rating`+`comment` |
| Feeds | `User.rating` (seller's aggregate, recomputed from all `Review` rows for that seller) | `Listing.ratingAvg`/`Listing.reviewCount` (recomputed from all `ProductReview` rows for that listing) |
| Public read | via `GET /users/:id/reviews` (**users module**, out of this module's 14) | via `GET /listings/:id/reviews` (**in scope**, #5 below) |

Both are written by **one buyer action** — a single `POST /orders/:id/review` call creates/updates one `Review` row and zero-or-more `ProductReview` rows (one per item in `dto.products`) inside one `$transaction` (`reviews.repository.ts:64-116`). A buyer is not choosing between "review the seller" and "review the product" as two separate flows — the DTO (`CreateOrderReviewDto`) carries both in one shape, and the service validates that every `products[].listingId` is actually `in` the order's own items (`BadRequestException` otherwise, `reviews.service.ts:70-74`).

**In practice only one half is ever populated**: the live mobile composer (`RateReview.tsx`) never sends `products` at all (see BR-REVIEWS-009 / gap below) — so `ProductReview` rows are, as of this analysis, effectively only created via direct API calls or seed data, never through the shipped buyer UI. `GET /sellers/me/product-reviews` and `GET /listings/:id/reviews` are both fully built and correctly implemented, but structurally starved of real data (`BRI-596`, open/Backlog).

## Endpoint-by-endpoint

### 1. `POST /orders/:id/review` (`reviews.controller.ts:35-44`) — `submitOrderReview`

- **Guard**: `JwtAuthGuard` only (per-route — this controller has no class-level guard, "routes mix public reads with per-route auth" per its own comment).
- **DTO**: `CreateOrderReviewDto` — `sellerRating` (required, int 1–5), `itemAsDescribed`/`shippingSpeed`/`communication` (optional int 1–5), `sellerComment` (optional, ≤2000 chars), `photos` (optional, ≤6 URLs), `products` (optional, ≤50 `ProductReviewItemDto { listingId, rating: 1-5, comment?: ≤2000 }`).
- **Preconditions, in order** (`reviews.service.ts:58-105`):
  1. Order must exist (`NotFoundException`).
  2. `order.buyerId === userId` (`ForbiddenException` otherwise — only the buyer can review their own order).
  3. **`order.status === 'delivered'`** — the only status check. `ForbiddenException` otherwise. **No other order-lifecycle field is checked** — see BR-REVIEWS-004 below re: `receiptConfirmedAt`.
  4. Every `products[].listingId` must be `in` the order's own item listing ids (`BadRequestException` — prevents reviewing a product you didn't buy on this order).
  5. `assertCommentClean` on `sellerComment` and on every product's `comment` — hard-blocks (403, `{ code: 'REVIEW_CONTENT_BLOCKED' }`) if the shared `common/utils/content-filter.util.ts`'s `classify()` flags **any** reason (phone/email/url/off_platform/address/profanity). Unlike chat's moderation (which only hard-blocks payment/contact and lets profanity through flagged-but-visible), a review comment is all-or-nothing — there is no partial save and no admin queue for a flagged-but-posted review, because neither `Review` nor `ProductReview` has an `isFlagged`/`flagReasons` column.
  6. `repository.submitReview` — upserts the `Review` row keyed on `(reviewerId, orderId)` and each `ProductReview` keyed on `(reviewerId, listingId)`, then recomputes `User.rating` and every touched `Listing.ratingAvg`/`reviewCount`, all inside one `$transaction`.
  7. A `P2002` from the upsert (a genuine concurrent double-submit on the same order) is caught and rethrown as `ConflictException('You have already reviewed this order.')` — added by `BRI-831`, see Prior-incident evidence below.
  8. Best-effort notification to the seller (`type: 'review_received'`, routed to their SELLING tab) — never throws on failure.
- **Response**: `201 { success: true }`.
- **Resubmitting for the same order does not error** — the upsert's `update` branch just overwrites the existing `Review`/`ProductReview` row in place (new rating/comment/photos replace the old ones silently, no "already reviewed" error on the happy path — only a genuine same-millisecond race trips the `P2002`→409). This is a conscious design (lets the composer be idempotent), but it also means the "duplicate submission" boundary case is really about **what UI surfaces the second submission**, not a hard API rejection. See REDB1-36 below — the mobile app does in fact let a buyer reopen a blank composer and "re-publish," which silently overwrites rather than erroring.

### 2. `GET /orders/:id/review` (`:48-52`) — `getMyOrderReview`

- **Guard**: `JwtAuthGuard`.
- Order must exist and belong to the caller (`NotFoundException`/`ForbiddenException`), then the `Review` row for that order must exist (`NotFoundException` — "No review found for this order."). **404 both when the order doesn't exist and when it exists but has no review yet** — a test must disambiguate by first asserting the order fetch succeeds via another endpoint.
- Response (`toOwnReviewDto`) includes a computed `editableUntil` = `review.createdAt + 30 days` — this is what `EditReview.tsx` reads to lock its form client-side; see BR-REVIEWS-005.
- Used as the Edit Review screen's prefill fetch, and separately by `OrderDetail.tsx` to render the "Your Review" card once `order.reviewSubmitted` is true.

### 3. `PATCH /orders/:id/review` (`:55-63`) — `updateOrderReview`

- **Guard**: `JwtAuthGuard`.
- **DTO**: `UpdateOrderReviewDto` — deliberately narrower than create: `sellerRating` (required), `sellerComment` (optional), `photos` (optional). **No `itemAsDescribed`/`shippingSpeed`/`communication`, no `products`** — editing only ever touches the seller-level review; per-product ratings/comments cannot be edited or added after the fact once the order review exists.
- Looked up by `orderId` (not review id) → `findReviewByOrder`. `review.reviewerId !== userId` → `ForbiddenException`. Then `assertWithinEditWindow(review.createdAt)` — `ForbiddenException` with a specific "30-day window has passed" message if `Date.now() - createdAt > 30 days`.
- `assertCommentClean(dto.sellerComment)` — same hard-block as create.
- `updateReview` recomputes `User.rating` only (no listing recompute — product ratings aren't touched by this endpoint).

### 4. `DELETE /orders/:id/review` (`:66-71`) — `deleteOrderReview`

- **Guard**: `JwtAuthGuard`. `HttpCode(200)` (not 204 — body is `{ success: true }`).
- Same ownership + 30-day-window checks as update. `deleteReview` hard-deletes the `Review` row **and** first deletes any `ReviewReport` rows pointing at it (`reviewType: 'seller', reviewId`) — there's no FK from `ReviewReport` to `Review`/`ProductReview` (polymorphic by design), so this cleanup is manual. Recomputes `User.rating` afterward. **Does not touch any `ProductReview` rows the same order may have created** — a buyer deleting their seller review within the window does not retract their per-product ratings.

### 5. `GET /listings/:id/reviews` (`:75-78`) — `getProductReviews`

- **No guard** — public, anonymous-accessible (buyer-facing listing page).
- **DTO**: `GetProductReviewsQueryDto` — `page`/`limit` (default 1/20, limit capped 50, both `@Type(() => Number)`-coerced).
- Page + aggregate (`avg`, `count`) run as a single `$transaction([findMany, aggregate])` — both against the same `where: { listingId }`, so the average shown always matches the page's underlying dataset (not just the visible page). No listing-existence check — an unknown/deleted `listingId` returns an empty page with `averageRating: 0`, not a 404.
- **This is the endpoint `BRI-596` reports as "always empty" in practice** — see gaps below.

### 6. `GET /sellers/me/product-reviews` (`:82-87`) — `getSellerProductReviews`

- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')` — live-checked against `isSeller` at request time (`apps/api/CLAUDE.md`'s `RolesGuard` note), not the JWT's static claim.
- **Not paginated** — returns every `ProductReview` across every one of the caller's listings in one response, grouped by listing (`Map` keyed by `listing.id`, insertion order = newest-review-first since the underlying query is `orderBy: createdAt desc`). Each group carries the listing's own denormalized `ratingAvg`/`reviewCount` (not recomputed from the group's contents — if a review was deleted by another path mid-session these two numbers and the visible review count could theoretically disagree momentarily, though both are normally updated together transactionally).
- Only consumed today by the **web** seller portal (`apps/web/src/app/seller/reviews/page.tsx` → `sellerApi.getProductReviews()`); **no mobile screen calls this endpoint** — Seller Hub's mobile Reviews screen shows seller-level reviews only (see Frontend usage below).

### 7. `DELETE /sellers/me/seller-reviews/:id` (`:90-96`) — `deleteOwnSellerReview`

- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- `findSellerReviewById` (by id, no seller scoping in the query itself) then an in-service ownership check (`review.sellerId !== sellerId` → `ForbiddenException`). Same hard-delete + report-cleanup + rating-recompute as the buyer/admin delete paths (`deleteSellerReview` repository method, shared across all three delete call sites).
- **No restriction on *which* reviews a seller can delete** — a seller can delete a 1-star, accurate, unflagged review of their own shop just as easily as a policy-violating one, and the delete silently raises their own rating on recompute. This is an explicit open product question (`BRI-566`), not yet resolved — see gaps.

### 8. `DELETE /sellers/me/product-reviews/:id` (`:99-105`) — `deleteOwnProductReview`

- Same guard/shape as #7, scoped via `findProductReviewWithSeller` (joins to `listing.sellerId` for the ownership check) instead of a direct `sellerId` column (ProductReview has none). Recomputes `Listing.ratingAvg`/`reviewCount`, not `User.rating`.
- **No mobile consumer** — only `apps/web/src/app/seller/reviews/page.tsx` (`sellerApi.deleteOwnProductReview`) calls this. Mobile's Seller Hub Reviews screen has no product-reviews tab at all.

### 9. `POST /sellers/me/seller-reviews/:id/reply` (`:108-118`) — `replyToSellerReview`

- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **DTO**: `ReplyReviewDto` — `replyText`, 1–1000 chars.
- Ownership check (`review.sellerId !== sellerId` → 403), then **one reply per review, immutable**: `if (review.replyText) throw new ConflictException('This review already has a reply.')`. No moderation/content-filter check is applied to `replyText` (unlike the review comment itself) — worth a dedicated test case.
- **This endpoint is fully implemented end-to-end (service + repository + schema columns `replyText`/`repliedAt` + a mobile API wrapper `sellersApi.replyToReview`) but has zero UI consumer in either app** — no screen on mobile or web renders a reply composer or displays `replyText` anywhere. Per Linear `BRI-98`, seller-reply-to-reviews was explicitly decided **OUT of MVP / Phase 2** by the Product Owner on 2026-07-27 ("DO NOT BUILD"), yet the backend (and a dead mobile API wrapper) shipped anyway. See gaps.

### 10. `POST /sellers/me/seller-reviews/:id/report` (`:121-131`) — `reportSellerReview`

- **Guard**: same seller-role guard.
- **DTO**: `ReportReviewDto` — `reason` (enum `spam|offensive|harassment|fake|other`), `note` (optional, ≤500 chars).
- Ownership check, then `createReviewReport({ reviewType: 'seller', reviewId, reporterId: sellerId, reason, note })` — a plain insert, `status` defaults to `'open'`. **Does not hide, flag, or otherwise alter the review itself** — it stays fully visible to everyone, exactly as before the report, with nothing distinguishing a reported review from an unreported one anywhere in any read path (`findSellerReviews`/`findProductReviewsAdmin`/`getProductReviews` never join `ReviewReport`).

### 11. `POST /sellers/me/product-reviews/:id/report` (`:134-144`) — `reportProductReview`

- Product-review mirror of #10, ownership via `listing.sellerId`. Same `createReviewReport` call, `reviewType: 'product'`.

### 12. `GET /admin/reviews` (`:148-153`) — `listForModeration`

- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles(Role.ADMIN)` — checked against the JWT's `role` claim directly (not a live DB lookup, unlike the `'SELLER'` string check — see `apps/api/CLAUDE.md`'s guard notes).
- **DTO**: `GetReviewsQueryDto` — `page`/`limit` (1/20 default, 50 cap), `q` (free-text), `type` (`'seller'|'product'`, defaults to seller when omitted).
- Free-text `q` searches `comment`, reviewer `username`, and (seller tab) seller `username` / (product tab) listing `title` — all `contains`+`insensitive`.
- **This endpoint lists `Review`/`ProductReview` rows themselves — it has no awareness of `ReviewReport` at all.** There is no "Reported" indicator, no filter, no count anywhere in this response shape. An admin paging through this list cannot tell which reviews (if any) a seller has reported — they'd have to query the database directly. Confirmed gap, matches `BRI-565` (open, Backlog) almost verbatim.

### 13. `DELETE /admin/reviews/:id` (`:156-162`) — `deleteSellerReview`

- **Guard**: ADMIN only. By id alone, **no ownership scoping of any kind** — any admin can delete any seller review. Same repository method as the seller's own delete path (`deleteSellerReview`): hard-deletes the `Review` row, deletes any `ReviewReport`s pointing at it first, recomputes `User.rating`.
- **No reviewer notification on delete, no reason recorded anywhere** — matches `BRI-566`'s open questions #2/#3 exactly ("When a review is deleted (by admin or seller), should the reviewer be told?... Neither action records a reason.").

### 14. `DELETE /admin/product-reviews/:id` (`:165-171`) — `deleteProductReview`

- Product-review mirror of #13. Recomputes `Listing.ratingAvg`/`reviewCount`.

## Business-rule cross-reference to Linear

`BRI-66` (Epic — Reviews) is the scope-resolution record: an earlier draft framed reviews as **mutual** (seller also rates buyer); the PO explicitly cut that scope on 27 Jul 2026 — **buyer-rates-seller only**. Matches the schema exactly: `Review.reviewerId` is always the buyer, `Review.sellerId` is always the one being rated; there is no seller→buyer review model anywhere. `BRI-96` additionally flags this cut scope as "a real gap, not building a seller-rates-buyer ticket without source material" — i.e. the PRD itself expected mutual reviews at an earlier stage, so a tester should not be surprised to find this absent, but it is a documented, not silent, scope cut.

`BRI-96` ("Leave a Review") states **"7-day window after order completion to submit a review"** as a confirmed business rule. **The code enforces no such deadline** — `submitOrderReview`'s only time-shaped check is `order.status === 'delivered'`, with no comparison against `deliveredAt`/`receiptConfirmedAt`/any elapsed-time field. A buyer can submit a first review for a `delivered` order regardless of how long ago it was delivered. This is a genuine **spec-vs-code conflict**, not merely an untested edge — flagged in business-rules.json as `BR-REVIEWS-003` with `conflict` evidence classification.

`BRI-97` ("Manage your review") confirms the **30-day edit window** 1:1 against `EDIT_WINDOW_MS` in code, and confirms "one review per order, enforced" (now true post-`BRI-785`/`BRI-831`) and "admin can delete policy-violating reviews" (true, `BRI-111`) — but explicitly leaves "whether the reviewer is notified when admin deletes their review" as an **open question**, unresolved as of this analysis (matches the code: no notification exists on any delete path).

`BRI-565`/`BRI-566` are two still-`Backlog`, `open-question`-labelled tickets that this analysis independently confirms against the current code line-for-line: no admin-side visibility into `ReviewReport`, no restriction on seller self-deletion of negative reviews, no notification or reason-recording on any delete. Both tickets' own "Technical notes" sections cite the exact files this analysis also read (`reviews.service.ts`, `reviews.repository.ts`, `SellerHubReviews.tsx`) — independent confirmation, not a new finding, but worth citing as corroboration.

`BRI-98` (seller reply) is **Canceled** in Linear with an explicit "DO NOT BUILD" header — yet `POST /sellers/me/seller-reviews/:id/reply` is fully built server-side, with schema columns and a mobile API wrapper, yielding a backend-complete, UI-dead endpoint. See gaps.

`BRI-596` (item-page reviews always empty) is corroborated exactly by reading `RateReview.tsx`'s `submit()` — it constructs a payload with `sellerRating`/`itemAsDescribed`/`shippingSpeed`/`communication`/`sellerComment` and **never includes a `products` array**, so no `ProductReview` is ever created by the shipped composer. `GET /listings/:id/reviews` and `GET /sellers/me/product-reviews` are both correctly implemented against data that the live app never produces.

## Prior-incident evidence (per the task's lead) — BRI-785 / BRI-831

The manual-sql file `2026-10-27-fix-review-unique-order-constraint.sql` is the tail end of a two-ticket incident, not an isolated patch:

1. **`BRI-785`** — "Admin Reviews: only the latest review is shown when a buyer reviews the same seller on two orders." Root cause: `Review`'s original unique constraint was `@@unique([reviewerId, sellerId])` — uniqueness on the **buyer–seller pair**, not the order. A second order from the same seller silently overwrote the first review's row (upsert semantics on the wrong key) — rating, date, and comment all destroyed, with the seller's review count staying flat instead of incrementing. Fixed in code/schema by moving the constraint to `@@unique([reviewerId, orderId])` and keying `submitReview`'s upsert on `reviewerId_orderId` — but **the matching migration was never written** (flagged in the fix doc's own "Not fixed here" section).
2. **`BRI-831`** — "Internal server error when publishing a review," Urgent/Blocker. Direct consequence of #1's unshipped migration: the real database still only had the old `Review_reviewerId_sellerId_key` index, so every `ON CONFLICT ("reviewerId","orderId")` the upserting code issued had no matching constraint to attach to — Postgres rejected it outright (`42P10`), which is not a Prisma `P2002`/any `HttpException`, so it fell straight through `AllExceptionsFilter`'s generic-500 branch. **Every single review submission failed**, regardless of content, until the manual-sql fix was applied (`DROP INDEX … Review_reviewerId_sellerId_key` / `CREATE UNIQUE INDEX … Review_reviewerId_orderId_key`) via `prisma db execute` + `prisma migrate resolve --applied`. The fix doc also added the `P2002`→`ConflictException` catch now visible in `submitOrderReview` (step 7 above), for the *remaining*, narrower race (two concurrent submits for the literal same order).
3. **Current DB state**: per the manual-sql file's own pre-check, the real (dev) database had only 2 `Review` rows total at the time of the fix, none sharing an `orderId` — so the index swap was confirmed non-destructive. **The real QA database (`api-qa.redspur.com`) was not confirmed patched** in the same pass — `BRI-831`'s write-up explicitly flags this as still outstanding, reachable only via SSH from inside the QA AWS environment, distinct from the locally-reachable `Redspur-qa` lookalike on the shared RDS (which *was* checked and found to have the same stale constraint, but is not the real QA DB). **A tester hitting an unexpected 500 on every review submission in a QA-like environment should check this constraint first** before assuming a new regression.

Current code (read end-to-end, `reviews.repository.ts:50-116` + `reviews.service.ts:58-118`) correctly reflects the post-fix state: `(reviewerId, orderId)` uniqueness, `P2002`→409 handling. **Nothing here is a currently-reproducible bug** — it's closed, but the schema/migration-drift pattern (code and manual-sql agree; the generated migration history may not) is exactly what `docs/ops.md`'s "no migration history" gotcha warns about, and worth a smoke test against any freshly-provisioned environment.

## Frontend usage

### Mobile

- `apps/mobile/src/services/reviewsApi.ts` — thin wrapper over `#1-5` (buyer-facing + public listing reviews) through `request<T>()`.
- `apps/mobile/src/services/sellersApi.ts` — seller-facing reviews section: `getReviews` (actually `GET /users/:id/reviews`, **users module**, not this one), `deleteShopReview` (#7), `reportShopReview` (#10), `replyToReview` (#9, **dead code** — no screen calls it).
- `apps/mobile/src/screens/profile/RateReview.tsx` — the composer (#1). Submits `sellerRating`+ 3 optional sub-ratings + `sellerComment`; **never sends `photos` or `products`** despite both being supported by the DTO (photos: the screen has no photo-picker UI at all; products: see BRI-596 above). On success, calls `useOrders.getState().markReviewed(order.id)` — a **client-only** optimistic flag (see BR-REVIEWS-016/gaps — this is not backed by any real server field tied to the `Review` model).
- `apps/mobile/src/screens/profile/EditReview.tsx` — #2 (prefill) + #3 (save) + #4 (delete). Correctly reflects the server's `editableUntil` for its lock state (`isLocked`).
- `apps/mobile/src/screens/profile/OrderDetail.tsx` — reads `order.reviewSubmitted` (client-derived, see below) to decide whether to show the "Rate & review" CTA (gated additionally on `order.receiptConfirmed`, a check the server's own `submitOrderReview` does **not** itself enforce — see BR-REVIEWS-004) or the "Your Review" card (fetches #2 when `reviewSubmitted` is true).
- `apps/mobile/src/screens/home/AllProductReviews.tsx` — #5 (public listing reviews), paginated `FlatList`.
- `apps/mobile/src/screens/seller/hub/SellerHubReviews.tsx` + `ReportReviewSheet.tsx` — #7 (delete) and #10 (report) only. **No reply UI, no product-reviews tab** on mobile at all — #6/#8/#9/#11 have zero mobile consumers.

### Web

- `apps/web/src/lib/api.ts`'s `adminApi` — #12 (`getReviews`), #13 (`deleteReview`), #14 (`deleteProductReview`). Consumed by `apps/web/src/app/admin/reviews/page.tsx` (tab-per-type, search, delete-with-confirm — no "Reported" affordance anywhere, matching the gap above).
- `apps/web/src/lib/sellerApi.ts` — `getReviews` (`GET /users/:id/reviews`, users module), `getProductReviews` (#6), `deleteShopReview` (#7), `deleteOwnProductReview` (#8), `reportShopReview` (#10), `reportProductReview` (#11). **No `replyToReview`/reply method exists in `sellerApi.ts` at all** — the web seller portal has no reply affordance either, consistent with mobile. Consumed by `apps/web/src/app/seller/reviews/page.tsx` — the only UI anywhere that exercises #6/#8/#11.

## Rating aggregation — cross-reference (sellers module, read-only)

`apps/api/src/sellers/sellers.service.ts` (lines ~1267, 1309) and `sellers.repository.ts` (`rating: true` in a `select`) read `User.rating` — the exact column this module's `recomputeSellerRating` writes — for the seller admin list and (presumably) shop-profile-adjacent responses. This confirms the aggregate this module maintains is consumed outside the module (as the task expected), but the `sellers` module itself is owned by another agent and not further traced here.
