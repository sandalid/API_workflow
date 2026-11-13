# Module: listings (`apps/api/src/listings/`)

Covers `listings.controller.ts` (21 routes) + its sub-controller `listing-stats.controller.ts` (5 routes) = **26 endpoints**. Both controllers share `@Controller('listings')` and are registered together in `listings.module.ts:41` (`controllers: [ListingsController, ListingStatsController]`, in that order). Paired module: `inventory` (see `modules/inventory.md`).

Source files read in full: `listings.controller.ts`, `listing-stats.controller.ts`, `listings.service.ts` (2191 lines), `listings.repository.ts` (1179 lines), `listing-presence.service.ts`, `listing.constants.ts`, every file under `listings/dto/`. Also read: `apps/api/prisma/schema.prisma` (`Listing`, `ListingImage`, `Inventory`, `InventoryAdjustmentHistory` models, `ListingStatus` enum), `apps/mobile/src/services/listingsApi.ts`, `apps/mobile/src/services/visualSearchApi.ts`, `apps/web/src/lib/sellerApi.ts`, `apps/web/src/lib/api.ts`.

## Architecture recap specific to this module

- **No class-level guard on `ListingsController`** (`listings.controller.ts:42`, comment: "most routes are public. Auth applied per-route only."). Guard is decided per-route; see the endpoint table.
- **Routing order verified safe.** `listings.controller.ts` registers write/admin routes first (lines 70–169: create, delete, relist, status, update, approve, reject), then public browse routes in this literal order (lines 186–390): `GET /` → `GET /search` → `GET /price-bounds` → `POST /visual-search` → `POST /search/text-semantic-preview` → `GET /mine` → `GET /:id/open-offers` → `GET /:id/views` → `GET /:id` → `GET /:id/likes` → `GET /:id/comments` → `POST /:id/like` → `DELETE /:id/like` → `POST /:id/comments`. Every literal-segment path that could collide with `:id` (`search`, `price-bounds`, `mine`) is declared before `GET /:id` (line 374), and NestJS/Express match by full path shape (segment count + literal-vs-param), so `likes`/`comments`/`open-offers`/`views` (two segments) never collide with the one-segment `:id` pattern regardless of declaration order — the in-file comments calling this out (lines 61, 171, 323, 343, 356) are accurate, not aspirational. `listing-stats.controller.ts` similarly declares `GET /mine/views` and `GET /mine/watchers` (listing-stats.controller.ts:32,40) before `GET /:id/watchers` (listing-stats.controller.ts:48) — same safe pattern. **No bug found here.**
- **Buyer-visible status set**: `LIVE_LISTING_WHERE` / `NOT_DELETED` (`listing.constants.ts:66-92`) = `status IN ('approved','active')` AND `deletedAt IS NULL` AND seller has no `deletionScheduledFor` (BRI-375 — a seller mid-account-deletion vanishes from discovery the moment they confirm, not when the purge runs). `ListingStatus` enum (`schema.prisma:36-45`): `draft | active | pending_approval | approved | rejected | inactive | sold | reserved`. `active` is explicitly "grandfathered — treated as approved for visibility" per the schema comment.
- **The buyer-facing DTO does NOT flatten lifecycle status to a 3-way enum as mobile's `utils/listingState.ts` assumes it mirrors** — in fact the API DTO (`toListingDto`/`toListingListDto`, `listings.service.ts:234-238,293-294,343-344`) returns BOTH a flattened `status: 'available'|'sold'|'reserved'` (via `mapStatus()`) AND the full `listingStatus: ListingStatus` field side by side. `mapStatus()` maps everything that isn't literally `sold` or `reserved` — including `draft`, `pending_approval`, `rejected`, `inactive` — to `'available'`. So a client that reads only `status` (not `listingStatus`) sees a paused/draft/rejected listing as `available`, which is exactly the trap `apps/mobile/CLAUDE.md`'s `utils/listingState.ts` note describes and exactly what caused BRI-44 (paused listing rendering Buy Now/Make Offer). The real, authoritative field for "is this live" is `listingStatus`, not `status`.

## Prisma models in play

- `Listing` (`schema.prisma:723-862`): soft-deleted via `deletedAt`; `price`/`originalPrice`/`shippingPrice` are 32-bit Postgres `Int` (hence `MAX_PRICE_CENTS = 2_147_483_647`, BRI-480); `commissionRateBps` stamped once at create/relist and never rewritten (BRI-352); `reservedUntil` only meaningful when `status = 'reserved'`.
- `ListingImage`, `ListingAttributeValue`/`FilterAttributeValue` (taxonomy filter answers, BRI-356), `Inventory` (1:1, see `modules/inventory.md`), `InventoryAdjustmentHistory`.
- `Like` (unique `(userId, listingId)`), `Comment`, `ListingEvent` (type `view`, used for Views/Trending), presence is Redis-only (no Prisma model).

---

## Endpoint-by-endpoint

### `POST /listings` — `listings.controller.ts:70` → `ListingsService.createListing` (`listings.service.ts:958`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **DTO**: `CreateListingDto` (`dto/create-listing.dto.ts`) — title 3–60 chars (trimmed before length check, BRI-575), description 10–2000, price/originalPrice/shippingPrice ints 0/100–2,147,483,647 (BRI-480), `brandId` **required** (BRI-326), `categoryId` required, `subcategoryId`/`typeId` optional but validated against the category tree, `imageUrls` 1–10 valid http(s) URLs (BRI-489 lowered cap from 12→10; `require_tld:false` for localhost dev, BRI-295), optional `videoUrl` (≤15s/≤50MB enforced client-side + at upload time, not here), `attributes` ≤30 `{slug,value}` pairs.
- **Business logic**: validates category/subcategory/type/brand existence and tree membership (400 on any miss, not a raw Prisma FK 500); runs `AiService.checkProhibited` on title/description/material/color/era/tags as a server-side backstop for "Fill in Manually" (BRI-226); screens all photos for weapons/blur server-side, fetching Redspur-hosted URLs back as data URLs (fails closed — 500, nothing saved, if the screen itself is down); rejects any new photo URL that isn't a Redspur upload unless some existing listing already has it (BRI-630/631); reads `PlatformSettings` fresh — `price >= highValueThresholdCents` (default $2000) ⇒ `pending_approval`, else `approved` (unless client explicitly requested `draft`); resolves `attributes` against the listing's subcategory/type, 400 on anything the tree doesn't offer; stamps the **current** `commissionRateBps` permanently.
- **Side effects (non-draft only)**: seller notification (`listing_pending` or `listing_approved`), image+text embedding enqueue (best-effort, swallowed on failure), saved-search match + follower "new listing" alert fired only when the listing publishes straight to `approved`/`active`.
- **Response**: `201`, `toListingDto(raw)`.
- **Frontend**: mobile `listingsApi.createListing` (`listingsApi.ts:256`). No web caller found in this scope (web's sell flow does not exist — "no public buyer storefront", per `apps/web/CLAUDE.md`).

### `DELETE /listings/:id` — `listings.controller.ts:86` → `ListingsService.deleteListing` (`listings.service.ts:2138`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **Ownership**: `findByIdForOwner(id, sellerId)` — 404 "Listing not found or not owned by you" for both "doesn't exist" and "someone else's" (no existence leak).
- **Blocks (409)**: any `OrderItem` row for the listing (`hasOrders`), or an `accepted` offer (`hasAcceptedOffer` — a committed sale even pre-payment/pre-Order, BRI-46/LI36).
- **Soft delete** (`deletedAt = now()`, BRI-366): row survives for order history/data export; every open (`pending`/`countered`, `orderId: null`) offer is read BEFORE the delete, then explicitly cancelled via an event (`LISTING_OFFERS_CANCEL_EVENT` → `OffersService`, out of this module's scope) — holds released, buyers notified. Count returned as `offersCancelled`.
- Cache invalidated (`listing:<id>`), embedding-removal enqueued (best-effort).
- **Frontend**: mobile `listingsApi.deleteListing`; web `sellerApi.deleteListing` (`apps/web/src/lib/sellerApi.ts:419`).

### `POST /listings/:id/relist` — `listings.controller.ts:100` → `ListingsService.relistListing` (`listings.service.ts:1320`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **Ownership**: `findByIdForOwnerWithImages` (needs the photo set to copy) — 404 if not owned.
- **Current behavior — confirmed gap**: the only status it refuses is `draft` (`if (original.status === 'draft') throw ConflictException`). **It does NOT require `sold`.** A `relist` on a still-`active`/`approved`/`inactive`/`pending_approval`/`reserved` listing succeeds and republishes a full duplicate through `createListing` (new id, fresh commission rate, re-screened photos, possibly re-reviewed if above threshold) while the **original is left completely untouched** — so a live or paused item can be listed twice simultaneously. See **Gaps** — this is a confirmed, currently-open product/engineering gap (Linear `BRI-673`, status Backlog as of this analysis), not a misreading: the ticket's own "Technical notes" cite this exact method and confirm "only blocks draft; add a check that `original.status === 'sold'`" was never implemented.
- 400 if the original has zero photos (can't relist with no images).
- **Frontend**: mobile `listingsApi.relistListing` (`listingsApi.ts:270`), gated client-side in `apps/mobile/src/screens/profile/SellerListingDetail.tsx` on `!isPending` (also not sold-only, per the same ticket) — **client and server agree on the (wrong, per spec) behavior**, so this is not a client/server mismatch, just a shared gap.

### `PATCH /listings/:id/status` — `listings.controller.ts:116` → `ListingsService.updateListingStatus` (`listings.service.ts:1362`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **DTO**: `UpdateListingStatusDto` — `@IsEnum(ListingStatus)` only. **Accepts any of the 8 enum values**, not a restricted "seller-safe" subset.
- **Confirmed gap (significant)**: the service does **no transition-table validation**. It only branches on whether the request is a "pause" (`status ∈ {inactive, draft}` while the listing is currently `approved`/`active`) to decide whether to cancel open offers — every other requested status (including `approved`, `pending_approval`, `rejected`, `sold`, `reserved`, or `active` from any starting state) is written as-is via `updateListingStatusById` with **no side-effect guard at all**. Confirmed by `listings.service.spec.ts:1794,1796,1927,1935,1942-1958` which explicitly call `service.updateListingStatus(..., 'sold' as any)`, `'active' as any`, `'draft' as any` — the `as any` casts are the test author acknowledging these aren't values the DTO/mobile client would normally send, but the service accepts them regardless. Net effect: a seller can `PATCH /listings/:id/status {"status":"approved"}` to self-approve a `pending_approval` listing (bypassing `POST /:id/approve`'s `Role.ADMIN` guard entirely), or set `"sold"`/`"reserved"` with no real inventory/offer backing those states. See **Gaps**.
- **Pause side-effects** (when triggered): every open offer cancelled + holds released + buyers notified (same mechanism as delete), count returned as `offersCancelled`; **reactivating never re-reads/rewrites `commissionRateBps`** (BRI-352/BRI-366 — the locked rate survives any number of pause/reactivate cycles; only a true `relist` picks up a fresh rate).
- Cache invalidated; embedding index synced via `syncEmbeddingIndex(listingId, oldStatus, newStatus)` (first-ever non-draft transition ⇒ full re-embed + text re-embed; any other non-draft→non-draft ⇒ payload patch; →draft ⇒ removed from index).
- **Frontend**: mobile `listingsApi.updateListingStatus` (`listingsApi.ts:264`) — only ever sends `inactive`/`active`/`draft` in practice (no UI path sends `sold`/`approved`/`rejected`/`reserved`), so the gap is currently only exploitable via a direct API call, not through the shipped app. Web uses a **different** endpoint for the same concept (`PATCH /sellers/me/listings/:id/status`, `apps/web/src/lib/sellerApi.ts:412-417` — out of this module's scope, lives in `sellers`).

### `PATCH /listings/:id` — `listings.controller.ts:134` → `ListingsService.updateListing` (`listings.service.ts:1453`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **Hard block**: `status === 'sold'` ⇒ 409 "A sold listing cannot be edited" (BRI-634), checked before any other work/validation.
- **DTO**: `UpdateListingDto` — every field optional, same bounds as create. category/subcategory/type validated against the listing's state **after** this edit applies (not its current state) — so moving category+subcategory in one request is validated as a unit.
- **High-value threshold re-check, price edits only**: crossing **upward** over `highValueThresholdCents` while live (`approved`/`active`) demotes the listing to `pending_approval` and cancels its open offers (LI27); crossing back **downward** while `pending_approval` AND it has a prior `approvedAt` (i.e., was live once, not a first-ever review) auto-restores to `approved` with no second admin pass. An edit that doesn't touch `price` never re-evaluates the threshold or touches `commissionRateBps`.
- **Photo re-screen**: only re-runs the weapon/blur model when the **final photo set composition changes at all** (added or removed), not merely "when a new URL is added" — BRI-803 found a photo can read differently once a companion photo it was submitted alongside is removed. New photo ownership check (`assertNewPhotoUrlsAreOurs`) only applies to genuinely new URLs.
- **Attribute replace-vs-clear semantics**: sending `attributes` on an update **replaces the whole set**; moving the listing to a different subcategory/type without resending attributes **silently clears** the old answers (can't offer them anymore since the old attributes aren't reachable from the new place in the tree) — logged, not surfaced to the client as a warning.
- Price-drop notification to every liker when price genuinely drops on a still-live listing (BRI-52) — not gated on any user preference (none persists server-side yet).
- Three independently-guarded embedding triggers (image change ⇒ full reindex; other payload-relevant field change with no image change ⇒ payload patch; text-relevant field change ⇒ text reindex) — can fire 0–2 of these per call depending on exactly which fields changed.
- **Frontend**: mobile `listingsApi.updateListing`; web `sellerApi.updateListing` calls a **different** route (`PATCH /sellers/me/listings/:id`, out of scope) that itself likely proxies into this same service (not verified — sellers module is a different batch).

### `POST /listings/:id/approve` — `listings.controller.ts:147` → `ListingsService.approveListing` (`listings.service.ts:1399`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles(Role.ADMIN)` (the real `Role` enum value, not the string-literal `'SELLER'` the other routes use — `RolesGuard` checks `ADMIN` against the JWT's `role` claim directly, per `apps/api/CLAUDE.md`).
- Sets `approved`, stamps `approvedById`/`approvedAt`, clears any prior `rejectionReason`. Notifies seller, fires saved-search match + follower "new listing" alert (claimed once via `claimFollowersNotification`, race-safe), patches embedding payload.
- **Frontend**: web admin `adminApi` → `POST /listings/:id/approve` (`apps/web/src/lib/api.ts:147`). No mobile caller (admin-only action, no admin surface on mobile).

### `POST /listings/:id/reject` — `listings.controller.ts:159` → `ListingsService.rejectListing` (`listings.service.ts:1427`)
- **Guard**: same as approve, `@Roles(Role.ADMIN)`.
- **DTO**: `RejectListingDto` — `reason` 5–500 chars (mandatory, enforced at the DTO boundary; BRI-539 notes a *different*, as-yet-unfixed admin UI surface that doesn't pre-validate this before hitting the API).
- Sets `rejected`, stores `rejectionReason`, clears `approvedById`/`approvedAt`. Notifies seller with the reason inline in the push/email body.
- **Frontend**: web admin `adminApi` → `POST /listings/:id/reject` (`apps/web/src/lib/api.ts:151`).

### `GET /listings` — `listings.controller.ts:186` → `ListingsService.findMany` (`listings.service.ts:427`)
- **Guard**: `OptionalJwtAuthGuard` (public; richer behavior if a token is present).
- **DTO**: `GetListingsQueryDto` — `page`≥1 (default 1), `limit` 1–**50** (default 20); `sort` one of `best|newest|price_asc|price_desc|most_liked|trending` (default `newest`; `best` has no meaning off the search endpoint, falls back to `createdAt desc`); full facet set (brand/category/subcategory/type/seller/condition/size/material/color/era/freeShipping/minPrice/maxPrice/`attributes[]`); `status=sold` only valid together with `sellerId` (cross-field `@Validate`, REDB1-31 — one seller's own Sold-history tab, never a cross-seller sold feed).
- **Self-dealing exclusion**: a logged-in viewer's own listings are excluded, and (BRI-470) any seller they've hidden, UNLESS an explicit `sellerId` is passed (a directed shop-view always wins over the undirected-discovery exclusion).
- `sort=trending` routes to a dedicated repository method (`findTrending`) ranked by `ListingEvent` view-count in the last 72h, excluding listings newer than 2h (so a single early view can't top the rail) — not expressible as a Prisma `orderBy`.
- Pagination is real `skip`/`take` inside one `$transaction` alongside `count` (consistent total vs. page).
- **Frontend**: mobile `listingsApi.getListings`/`getListingsByBrand`/`getListingsByCategory`/`getListingsBySeller` (`listingsApi.ts:279-401`; the by-brand/by-category helpers are explicitly dead code per their own doc comment — BRI-457/BRI-435 moved both callers onto `searchListings` instead, left in place unused).

### `GET /listings/search` — `listings.controller.ts:214` → `ListingsService.search` (`listings.service.ts:488`)
- **Guard**: `OptionalJwtAuthGuard`.
- Same `GetListingsQueryDto` plus `q`. Default (keyword-only) path: every whitespace/comma/semicolon-delimited term must match title/description/tag (AND across terms, case-insensitive `contains` + exact tag match) — `tokenizeSearchQuery` keeps `Levi's`/`AT&T`/`long-sleeve` as one token (BRI-649) and drops punctuation-only tokens.
- **Hybrid path** (env-gated `HYBRID_SEARCH_ENABLED=true` AND `sort` ∈ `{best,newest,price_asc,price_desc}` AND non-empty `q`): runs keyword (`ts_rank_cd` raw SQL) and text-embedding (Qdrant) retrieval concurrently, fuses by **reciprocal rank** (never raw score), re-hydrates + re-filters the full fused set from Postgres before paginating (fixes an earlier filter-after-paginate bug class), then applies a lexical-relevance gate that exempts keyword-leg hits (already lexeme-justified) and only filters semantic-only hits lacking any literal term overlap (the "cake → Shoulder Bag" false-positive guard). Splits into `data` (every query term present) and `partialMatches` (some terms present via a semantic/synonym hit only — BRI-440, page-1-only "related to your search" shelf, never merged into `data`). The semantic leg degrades to keyword-only on any provider/Qdrant failure (never 500s the whole search) — logged with a `reqId` that ties together every log line for one request.
- **Frontend**: mobile `listingsApi.searchListings`/`countListings` (`listingsApi.ts:345-374`).

### `GET /listings/price-bounds` — `listings.controller.ts:253` → `ListingsService.findPriceBounds` (`listings.service.ts:484`)
- **Guard**: `OptionalJwtAuthGuard`. Same filter set minus pagination/sort; the incoming `minPrice`/`maxPrice` are explicitly accepted-but-ignored (BRI-408 — the bounds must describe the full choosable range, not the range already chosen). Returns `{minPrice, maxPrice}` in integer cents, both `null` if nothing matches. Reuses the exact same keyword-matching rule as `search()` when `q` is present, so the slider never disagrees with the grid it feeds.
- **Frontend**: mobile `listingsApi.getPriceBounds` (`listingsApi.ts:326`).

### `POST /listings/visual-search` — `listings.controller.ts:277` → `ListingsService.visualSearch` (`listings.service.ts:1697`)
- **Guard**: `OptionalJwtAuthGuard, VisualSearchThrottlerGuard` (dedicated rate limit beyond the global 100/min).
- **Multipart**: `FileInterceptor('image', memoryStorage, 10MB cap)`; 400 if no file. `VisualSearchQueryDto` carries the facet filters (no `q`, no `sellerId` — not meaningful for a photo).
- **Pipeline**: image moderation screen first (blocks prohibited content before any embedding spend) → `EmbeddingsService.classifyAndSearchByImage` (Qdrant top-500 candidates, category/brand classification with confidence tiers) → Postgres hydration+facet re-filter → optional soft-brand ranking boost (40–74% brand confidence nudges rather than excludes) → taxonomy filter with safeguards (an exact-match row, score ≥0.9, is never filtered out regardless of category/subcategory mismatch; a row that clearly outranks — by ≥0.05 — the best in-taxonomy row is kept even if off-taxonomy, BRI-813) → a 0.70 "close match" floor (below it, the whole result set is emptied rather than showing noise) → an optional one-shot vision "relevance judge" over the top 30 candidates when the best score is still below the exact-match floor → sort → paginate → a "catalog coverage" check (distinguishes "nothing matched" from "we don't carry this category/subcategory at all," surfaced as `catalogCoverage` in the response) → persists a `VisualSearchRequest` analytics row (cost/latency/every classification signal) best-effort.
- **Frontend**: mobile `visualSearchApi.search` (`apps/mobile/src/services/visualSearchApi.ts`), used from `apps/mobile/src/screens/photoSearch/PhotoSearchResults.tsx`. No web caller (no buyer storefront on web).

### `POST /listings/search/text-semantic-preview` — `listings.controller.ts:314` → `ListingsService.searchTextSemanticPreview` (`listings.service.ts:2057`)
- **No guard at all** at the decorator level — gated instead by a runtime `NODE_ENV === 'production'` check that throws `NotFoundException` (404s in prod, reachable with no auth in dev/staging). `TextSemanticPreviewDto.q`, 1–200 chars.
- Dev-only diagnostic: raw text-embedding tier, no fusion, no keyword leg, no pagination (top 20, as-is).
- **Frontend**: none found in the analyzed scope (by design — "dev-only isolated... quality-read endpoint", per its own doc comment).

### `GET /listings/mine` — `listings.controller.ts:326` → `ListingsService.findMyListings` (`listings.service.ts:461`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`.
- **DTO**: `GetMyListingsQueryDto` — `status` one of `active|pending|paused|drafts|sold` (default `active`), mapped to real `ListingStatus[]` via `MY_LISTINGS_STATUSES` (`listings.service.ts:66-76`): `active → [approved, active, reserved]` (an accepted-offer-pending-payment listing shows under Active, not invisible, per a prior bug fix), `pending → [pending_approval]`, `paused → [inactive]`, `drafts → [draft]`, `sold → [sold]`. `limit` max 50. `q` searches the seller's own titles, symbol-insensitive (`mens` finds "Men's") via a dedicated `regexp_replace`-based raw-SQL match (`findSellerTitleMatchIds`), capped at 100-char query / 10 terms.
- Not status-filtered to buyer-visible — owner sees their own drafts/pending/sold/paused freely (expected: it's their own inventory).
- **Frontend**: mobile `listingsApi.getMyListings` (`listingsApi.ts:406`).

### `GET /listings/:id/open-offers` — `listings.controller.ts:345` → `ListingsService.getOpenOffers` (`listings.service.ts:2100`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`. Ownership via `findByIdForOwner`.
- Returns `count`, `amountsCents[]` (open = `pending`/`countered`, no `orderId`), `hasAcceptedOffer`, `hasOrders`, `canDelete` (= neither), `blockedReason` (`'order'` wins over `'accepted_offer'` when both true) — exactly mirrors `deleteListing`'s actual 409 conditions so the seller's delete-confirm dialog can warn accurately before they commit (BRI-46/LI36 — previously the dialog under-counted and an "optimistic" delete could still bounce with a 409).
- **Frontend**: mobile `listingsApi.getOpenOffers`; web `sellerApi.getListingOpenOffers` (`sellerApi.ts:426`).

### `GET /listings/:id/views` — `listings.controller.ts:359` → `ListingsService.getViewsCount` (`listings.service.ts:2124`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`. Ownership via `findByIdForOwner`.
- Counts `ListingEvent` rows of type `view` for this listing; self-views are excluded **at write time** by `EventsService.screen` (outside this module), not filtered here — this endpoint is a plain count with nothing left to exclude (BRI-319).
- **Frontend**: mobile `listingsApi.getListingViews`.

### `GET /listings/:id` — `listings.controller.ts:374` → `ListingsService.findById` (`listings.service.ts:769`)
- **Guard**: `OptionalJwtAuthGuard` (public, richer for the owner/an admin).
- **Caching**: `listing:<id>` via `CACHE_MANAGER`, no explicit TTL override seen in this file (defaults to the cache module's configured default) — shared across **every** caller regardless of identity, which is exactly why the DTO can never include a requester-aware field like an offer count (comment at `listings.service.ts:284-290`).
- **Visibility gate runs AFTER the cache read, per request**: only `pending_approval` 404s for anyone but the owner or an admin (`HIDDEN_FROM_PUBLIC_STATUS`, BRI-636/BRI-46 LI26) — chosen deliberately as the *one* non-live status that goes fully dark, because it's the exact state a price-raise-across-threshold puts a previously-live listing into, and the spec calls for it to be fully hidden (not just CTA-disabled) until re-approved. `draft`/`rejected`/`inactive`/`sold`/`reserved` remain reachable via a direct `GET /:id` (not 404'd) — deliberately, to support a stale deep link/wishlist/chat reference with purchase CTAs disabled client-side (mobile's `utils/listingState.ts`), which is a separate, already-settled product decision this endpoint doesn't touch.
- Every write path that changes what this returns must call `ListingsService.invalidateCache` — an admin take-down path once skipped this and showed a stale `ACTIVE` detail page for ~15s after a successful take-down (BRI-438, now fixed; flagged here as a pattern any *new* write path to `Listing` must remember).
- **Frontend**: mobile `listingsApi.getListing` (token optional, but **must** be passed when showing the owner their own just-paused listing or the owner-check never runs and a legitimate owner 404s like an anonymous request, BRI-781); web `sellerApi.getListing`/`adminApi.getListing`.

### `GET /listings/:id/likes` — `listings.controller.ts:381` → `ListingsService.getLikes` (`listings.service.ts:817`)
- **No guard** (public). 404s on an unknown listing id rather than an empty array (BRI-520 — "no likes" and "bad id" must not read the same). No status gate beyond existence — a caller can list likes on a draft/paused listing if they know its id (no `isOwner` check either); low sensitivity (usernames/avatars only) but worth noting as not owner-scoped at all, unlike the writer side (`likeListing`).
- **Frontend**: mobile `listingsApi.getComments`/likes not directly exposed via a dedicated screen call found in this scope search ("no frontend reference found" for a dedicated likes-list screen; likes are primarily surfaced via `likeCount` on the listing DTO, not this endpoint).

### `GET /listings/:id/comments` — `listings.controller.ts:387` → `ListingsService.getComments` (`listings.service.ts:832`)
- **No guard** (public), no existence check at all (unlike likes — if the id doesn't exist, `prisma.comment.findMany` just returns `[]`, not a 404; **inconsistent with the likes endpoint's BRI-520 fix**, see Gaps).
- **Frontend**: mobile `listingsApi.getComments` (`listingsApi.ts:418`).

### `POST /listings/:id/like` — `listings.controller.ts:395` → `ListingsService.likeListing` (`listings.service.ts:793`)
- **Guard**: `JwtAuthGuard` only (any authenticated user, no role check — correct, buyers aren't a role).
- 404 if the listing doesn't exist OR its status is in `NON_LIKEABLE_LISTING_STATUSES = [draft, pending_approval, rejected, inactive]` (BRI-519 — liking a non-public listing used to leak its full detail via the buyer's own likes list and inflate a public counter on something nobody else could see). **`sold` and `reserved` are deliberately left likeable** — an open product question per the code's own comment (`listing.constants.ts:98-102`, "allow the like and show it in the list, or return an error" — not yet decided).
- 403 if the caller is the listing's own seller (BRI-329 — self-liking inflated `likesCount`/`watchersCount`/the feed's "saves" ranking signal).
- Idempotent at the repository level: `likeListing` repo method checks-then-creates inside one `$transaction`, returning the existing `Like` row (not erroring) on a repeat like; `likesCount` increments exactly once per real insert.
- **Frontend**: mobile `listingsApi.likeListing` — consumed by `likesStore.ts`'s optimistic toggle with the documented `pendingSync` promise-chain fix for BRI-290 (two rapid taps racing their network calls out of tap order). **Server-side note relevant to that bug**: the repository's like/unlike are each individually idempotent and atomic, but there is **no server-side serialization or idempotency key across a rapid like→unlike→like sequence from the same user** — correctness for that race currently lives entirely in the mobile client's `pendingSync` chain (per `apps/mobile/CLAUDE.md`), not in this endpoint; a second client (web, a script, a future partner integration) hitting this endpoint directly with the same rapid-toggle pattern would be exposed to the exact race BRI-290 fixed client-side only.

### `DELETE /listings/:id/like` — `listings.controller.ts:406` → `ListingsService.unlikeListing` (`listings.service.ts:812`)
- **Guard**: `JwtAuthGuard`. No existence/status/ownership check at all before unliking — a no-op (`{count: 0}`) if no `Like` row exists, which is harmless but means unliking a listing that was deleted/changed status after the like was created still "succeeds" silently.
- **Frontend**: mobile `listingsApi.unlikeListing`.

### `POST /listings/:id/comments` — `listings.controller.ts:417` → `ListingsService.addComment` (`listings.service.ts:2176`)
- **Guard**: `JwtAuthGuard`. **DTO**: `CreateCommentDto` — `text` 1–500 chars.
- 404 only if the listing truly doesn't exist (plain `findById`, no soft-delete bypass). **No status gate at all** — unlike `likeListing`'s `NON_LIKEABLE_LISTING_STATUSES` check, a comment can be posted on a `draft`/`pending_approval`/`rejected`/`inactive` listing the commenter should not even be able to see via `GET /:id` (which 404s `pending_approval` for non-owners) — i.e. a buyer who somehow has a `pending_approval` listing's id (e.g. leaked through another surface, or guessed) can comment on it despite `GET /listings/:id` refusing to show it to them. **No self-comment restriction either** (unlike likes' BRI-329 self-dealing check) — the listing's own seller can comment on their own listing. See **Gaps** — this is an asymmetry with the like endpoint's moderation posture, not confirmed as exploited by any known ticket, but the code-level inconsistency is real and verifiable.
- **Frontend**: mobile `listingsApi.postComment`.

### `GET /listings/mine/views` — `listing-stats.controller.ts:32` → `ListingsService.getMyViewsTotal` (`listings.service.ts:2133`)
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`. **DTO**: `ViewsRangeQueryDto` — optional ISO-8601 `from`/`to` window (Seller Hub period selector, BRI-319).
- **Frontend**: mobile `listingsApi.getMyViewsTotal`.

### `GET /listings/mine/watchers` — `listing-stats.controller.ts:40` → `ListingPresenceService.watchersForOwnerMany`
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`. **DTO**: `ListingIdsQueryDto` — comma-separated ids, 1–100, parsed from a single query string.
- Ids the caller doesn't own are silently dropped from the result rather than erroring the whole batch (`findOwnedListingIds` filters first).
- **Frontend**: mobile `listingsApi.getMyListingsWatchers`.

### `GET /listings/:id/watchers` — `listing-stats.controller.ts:48` → `ListingPresenceService.watchersForOwner`
- **Guard**: `JwtAuthGuard, RolesGuard` + `@Roles('SELLER')`. 404 if not owned (`findOwnedListingIds`).
- **Backing store**: Redis sorted set per listing (`listing:presence:<id>`, member=buyerId, score=last-heartbeat-ms), `PRESENCE_TTL_MS = 60_000` (two missed ~25s heartbeats expire a watcher). Every presence operation fails soft (logged, never throws) — a Redis blip degrades to "0 watchers," never a broken page.
- **Frontend**: mobile `listingsApi.getListingWatchers`.

### `POST /listings/:id/presence` — `listing-stats.controller.ts:56` → `ListingPresenceService.heartbeat`
- **Guard**: `JwtAuthGuard` (buyer-side, any authenticated user — not seller-gated, correctly, since any buyer can be "on" a listing). 204 No Content.
- 404 if the listing doesn't exist (via `findSellerId`, soft-delete-aware). **The listing's own seller's heartbeat is a silent no-op** (`if (sellerId === userId) return`) — same self-exclusion rule as Views, so a seller checking their own listing never inflates their own Watchers stat.
- **Frontend**: mobile `listingsApi.beatPresence`, called every ~25s while `ProductDetail` is focused (per `apps/mobile/CLAUDE.md`'s documented pattern).

### `DELETE /listings/:id/presence` — `listing-stats.controller.ts:64` → `ListingPresenceService.leave`
- **Guard**: `JwtAuthGuard`. 204. No existence check — a `zrem` on a Redis key that may not exist is a harmless no-op either way.
- **Frontend**: mobile `listingsApi.leavePresence`.

---

## Business rules

See `fragments/catalog-listing.business-rules.json` (`BR-LISTINGS-001`..`030`) for the full, evidence-tagged list — summarized narratively above per endpoint.

## Gaps, flows, test scenarios, dependency map

See the four sibling fragment files for cross-referenced detail:
- `fragments/catalog-listing.gaps.md`
- `fragments/catalog-listing.flows.md`
- `fragments/catalog-listing.test-scenarios.md`
- `fragments/catalog-listing.dependency-map.json`
