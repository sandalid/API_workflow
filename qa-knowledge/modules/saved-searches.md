# Module: Saved Searches

6 endpoints, `apps/api/src/saved-searches/` (`saved-searches.controller.ts` — `@Controller()` root, routes carry full paths — `saved-searches.service.ts`, `saved-searches.repository.ts`, `saved-search-match.util.ts`, `dto/`). Backed by the `SavedSearch` Prisma model.

Analyzed against commit `91e0447b`. Ticket evidence: `BR35`/`BR33`/`BRI-494`/`BRI-662`/`BRI-224` cited directly in source comments.

## Guard

`@UseGuards(JwtAuthGuard)` at class level — every route requires authentication, no public routes in this controller.

## 1. `POST /saved-searches` (`:29-37`) — `create`

- **Body**: `CreateSavedSearchDto` — `name` (required, 1-120 chars, **trimmed before validation** so a whitespace-only name fails like an empty one — `BRI-494`), `q` (optional free text), `categoryId`/`brandId` (optional, existence-checked against live `CategoriesService`/`BrandsService` lookups — a non-existent id is a clean 400 "Category/Brand not found" rather than a raw Prisma FK-constraint 500), `condition` (optional, `@IsIn` the Prisma `Condition` enum), `size` (optional string), `minPrice`/`maxPrice` (optional, integer cents, `@Min(0)`), `sort` (optional, one of `newest|price_asc|price_desc|most_liked` — the API-level `SortOption`, stored as-is, mobile converts its own internal sort-key representation before saving), `alertsEnabled` (optional boolean, **defaults to `true`** at the service layer if omitted).
- **No ownership input accepted** — `userId` comes from the JWT (`req.user.id`), never the body.
- **Response**: the created row via `toDto` (id, name, q, categoryId, brandId, condition, size, minPrice, maxPrice, sort, alertsEnabled, newMatchCount=0, lastViewedAt=null, createdAt).

## 2. `GET /me/saved-searches` (`:39-43`) — `list`

- Lists only the caller's own saved searches, newest-first (`createdAt desc`). No pagination params accepted — the full set is returned every call (same unbounded-list pattern noted elsewhere in this knowledge base for `GET /offers`; not flagged as broken, but worth a load-shape test for a very prolific account).

## 3. `PATCH /saved-searches/:id` (`:45-53`) — `update`

- **Ownership enforced via `loadOwned`**: 404 if the row doesn't exist, **403** (not 404) if it exists but belongs to another user — this is a cleanly distinguishable two-path error, contrast with `promotions`' collapsed single-message approach documented in `modules/promotions.md`.
- **Body**: `UpdateSavedSearchDto` — **only `name` and `alertsEnabled` are editable.** This is an explicit business rule (`BR33`, stated verbatim in the DTO's own code comment): *"Filters aren't editable here; a new set of filters means a new saved search."* A test asserting `categoryId`/`q`/`minPrice`/etc. can be changed via this endpoint will fail — not a bug, a deliberate API design constraint. The global `ValidationPipe`'s `forbidNonWhitelisted: true` means sending any other field in the body produces a 400, not a silent no-op.
- Same name-trim/empty-rejection rule as create (`BRI-494`).

## 4. `DELETE /saved-searches/:id` (`:55-63`) — `remove`

- Same `loadOwned` ownership check. Hard delete (`repo.delete`, no soft-delete flag on this model). Returns `{ success: true }`, not 204.

## 5. `GET /saved-searches/:id/results` (`:65-74`) — `getResults` (`BR35`)

- Same ownership check. **Re-runs the saved filter live** against the current listings catalog on every call — `this.listings.search(...)` if `q` is set, `this.listings.findMany(...)` otherwise (both methods belong to `ListingsService`, already analyzed in `modules/listings.md` — cross-reference its pagination/filter semantics rather than re-deriving them here). **Not a cached/precomputed result set** — this directly resolves what an earlier open question in this project's notes characterized as ambiguous: results are computed fresh, not stored.
- **`isNew` flag**: each returned listing is annotated `isNew: listing.createdAt > lastViewedAt` (only when `lastViewedAt` is non-null — a saved search that has never been viewed treats nothing as "new," since there's no baseline to compare against). This is the mechanism the `newMatchCount` badge and "mark viewed" endpoint coordinate with.
- **Query**: `GetSavedSearchResultsQueryDto` — `page` (default 1), `limit` (default 20, max 100 — note this is a **different max than `GetFeedQueryDto`'s 50** in the `feed` module; not an inconsistency flag, just worth knowing two different caps exist in this knowledge base for superficially similar pagination params).

## 6. `POST /saved-searches/:id/mark-viewed` (`:76-82`) — `markViewed`

- Same ownership check. Sets `lastViewedAt = now()` and resets `newMatchCount` to 0 in one update. This is what makes the "new since last view" badge/count disappear after the buyer opens the results — purely a read-receipt operation, no interaction with the listings catalog itself.

## Non-HTTP: the async match-notification trigger (`notifyMatches`)

Not an endpoint, but the module's most consequential business logic and essential for flow-tracing: called from `ListingsService` when a listing transitions to live (not independently re-verified in `listings.service.ts` in this pass — cross-reference during consolidation). For every `alertsEnabled: true` saved search whose **structured facets** (category/brand/condition/size/price-range) SQL-pre-filter-match the new listing (`findMatchingCandidates` — explicitly excludes the listing's own seller from ever matching their own search, confirmed in the repository query's `userId: { not: listing.sellerId }`), the **free-text `q` component is additionally checked in-memory** via `listingMatchesQuery` (not read in this pass — a separate util file, `saved-search-match.util.ts`) before a `saved_search_match` notification fires and `newMatchCount` increments. **Best-effort by design** — the service's own doc comment states callers wrap this so a matching failure never breaks listing creation; a thrown error inside `notifyMatches` is swallowed upstream, not surfaced to the seller creating the listing.

- **Notification copy** (`matchNotificationCopy`, `BRI-662`): title names the search (falling back to its `q` keywords, then a generic label if both are blank — a legacy pre-`BRI-494` row could still hold a blank `name`, though new rows can't); body names the specific matched listing and its price. This was a real fix: the push used to read a generic "New match"/repeated-title body with nothing listing-specific, so multiple matches for one search were word-for-word identical notifications.

## Frontend usage

### Mobile (only consumer found)

- `apps/mobile/src/services/savedSearchesApi.ts` — 1:1 wrappers for all 6 endpoints, typed response mirrors the server DTO closely (`SavedSearch` interface matches `toDto`'s shape field-for-field).

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` — confirmed by grep (zero matches for the literal routes). The admin/seller portal has no saved-search surface.

## Business-rule-relevant findings for consolidation

- **BR-SAVED-SEARCHES-001**: only `name`/`alertsEnabled` are editable post-creation (`BR33`) — a filter change requires creating a new saved search, not updating the existing one.
- **BR-SAVED-SEARCHES-002**: results are computed live on every `GET .../results` call, never cached/precomputed — reuses the exact same `ListingsService` search/findMany path a direct `GET /listings`/`GET /listings/search` call would use, so its filter/pagination semantics inherit whatever is true of that module.
- **BR-SAVED-SEARCHES-003**: a seller's own listing can never trigger a match notification against their own saved search (hard exclusion in the SQL pre-filter, not merely a client-side convention).
- **BR-SAVED-SEARCHES-004**: match notification is best-effort/non-blocking — a failure here must never surface as a listing-creation error to the seller (confirm this contract holds in `modules/listings.md`'s go-live transition code during consolidation, since this module's own code only documents the intent, not the calling side's actual error-swallowing).
