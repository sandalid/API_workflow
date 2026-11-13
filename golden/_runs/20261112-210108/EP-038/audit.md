# Endpoint #EP-038 - GET /listings/:id

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route and guard: `listings\listings.controller.ts:374` (`@Get(':id')`), `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`), `listings\listings.controller.ts:376` (`findById`). The handler passes `req.user` to the service.
- Service: `listings\listings.service.ts:769` (`async findById`). The visibility gate is at `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`), and the constant is defined at `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`).
- Mapper: `listings\listings.service.ts:240` (`toListingDto`).
- Repository: `listings\listings.repository.ts:692` (`findById`). The soft-delete filter is `listings\listings.repository.ts:694` (`NOT_DELETED`), defined at `listings\listing.constants.ts:68` (`NOT_DELETED`).
- Cache: the service caches the DTO under `listing:<id>` and shares it across all callers (`listings\listings.service.ts:770` (`cacheKey`)).
- Tests: `listings\listings.service.spec.ts:911` (`describe('findById'`).

## Declared contract
- Path param: `id` (string, no format or length constraint). The code takes it as a bare `@Param('id') id: string` (`listings\listings.controller.ts:376` (`@Param('id')`)), and there is no DTO or pipe.
- Headers: an optional `Authorization` bearer token. The guard tells the service who is asking; it does not reject anonymous callers.
- Query and body: none.
- Success response (200): the `toListingDto` object. Fields are listed under "Response contract" below.
- Errors in code: 404 "Listing not found" when the row is missing or soft-deleted, or when the status is `pending_approval` and the viewer is neither the owner nor an admin. There is no 401, 403 or 400 path.
- OpenAPI: `schemathesis\spec\openapi.pretty.json:1551-1572`. One path param `id` (string) and only a `200` response with an empty description and no schema. No 404 is documented.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | The visibility gate covers only `pending_approval`. `draft`, `rejected` and `inactive` listings are returned to anyone, including anonymous callers. This contradicts the sheet Title (see the matrix). | branch | not a B/A category; requirement conflict | `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`), `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`) | backend | high |
| 2 | Soft-deleted ("removed") listings give 404 for every caller, including the owner and admin. The repository filters `deletedAt: null`, so the "owner or Admin" exception does not apply to removed listings. | branch | not a B/A category; behaviour note | `listings\listings.repository.ts:694` (`NOT_DELETED`) | backend | high |
| 3 | `req.user.role` is compared with `Role.ADMIN`. The viewer is typed `{id, role}` and I did not trace what the JWT strategy puts on `req.user`. | branch | not a B/A category | `listings\listings.service.ts:785` (`isAdmin`) | backend | med |
| 4 | No unused request items. `id` is used; there is nothing else to send. | query/body | none | `listings\listings.controller.ts:376` (`@Param('id')`) | all | high |
| 5 | Response fields consumed by neither client: not fully assessed (see "Could not verify"). Mobile `ListingDto` reads `listingStatus`, `watchersCount`, `negotiable` and `attributes` (`apps\mobile\src\services\listingsApi.ts:54` (`ListingDto`)). Web has its own `ListingDetail` and `AdminListingDetail` types. | response | A3 | `apps\mobile\src\services\listingsApi.ts:54` (`ListingDto`), `apps\web\src\lib\types.ts:280` (`AdminListingDetail`), `apps\web\src\lib\sellerApi.ts:104` (`ListingDetail`) | both | low |
| 6 | `currency` is the constant `'USD'`. | response | B4 | `listings\listings.service.ts:274` (`currency`) | backend | high |
| 7 | `watchersCount` always equals `likeCount`. Both are set from `_count.likes`. | response | B4 (duplicate value) | `listings\listings.service.ts:280` (`likeCount`), `listings\listings.service.ts:283` (`watchersCount`) | backend | high |
| 8 | Mobile `ResumeDraft` and `SellerListingDetail` call `getListing`. `ResumeDraft` passes no token, so an owner viewing their own `pending_approval` listing gets 404. The `SellerListingStatus`, `SellerListingDetail` and `SellerEditPrice` calls do pass a token. | branch | A1 (token not sent in one flow) | `apps\mobile\src\screens\profile\ResumeDraft.tsx:39` (`getListing`) | mobile | med |

## Looks unused but keep (and why)
- `negotiable` and `minOfferPercent` are consumed by the buyer's Make Offer flow. The code comments cite BRI-202 and BRI-38 (`apps\mobile\src\services\listingsApi.ts:77` (`negotiable`), `listings\listings.service.ts:300` (`minOfferPercent`)). I did not trace the UI readers.
- `subcategoryId` and `typeId` serve the seller edit flow (`listings\listings.service.ts:248-251`).
- `watchersCount` is for the seller detail screen (`apps\mobile\src\services\listingsApi.ts:62` (`watchersCount`)).

## Could not verify (and what I checked)
- Per-field A3 for both clients. I checked the mobile `ListingDto` and the call sites, but did not trace every screen that reads each field. I did not open the web `ListingDetail` or `AdminListingDetail` field lists or their page components.
- Whether the JWT strategy populates `req.user.role` with the same `Role` enum values the service compares against (`listings\listings.service.ts:785` (`isAdmin`)).
- Flows 3, 18 and 26: I had no flow definitions to check against.
- Whether the QA environment's cache TTL or `invalidateCache` covers every status transition. The KB mentions a past stale-cache bug (BRI-438), and I did not re-verify it.

## Knowledge base cross-check
- BR-LISTINGS-021 (`qa-knowledge\business-rules.json:235`) says every write path that changes the detail response must call `invalidateCache`. The evidence line it cites, `listings\listings.service.ts:769`, matches `findById`, but I did not verify the write paths. This is a stale-visibility lead for tests: a status change followed by a read within the cache window.
- BR-LISTINGS-023 (`qa-knowledge\business-rules.json:237`) says liking a non-public listing 404s. That is a different endpoint. It does confirm that `draft`, `pending_approval`, `rejected` and `inactive` are treated as non-public in `likeListing`, while `findById` hides only `pending_approval`. I did not re-open `listings\listings.service.ts:793` beyond line 799 (its comment cites BRI-519), which says non-public listings "must 404 here exactly like it would on GET /listings/:id". That comment conflicts with the actual gate, which hides only `pending_approval`.
- The KB has no dedicated endpoint row for GET /listings/:id that I found. I only searched by pattern.

## Sheet check
- Method and path match: `GET /listings/:id` (`listings\listings.controller.ts:374` (`@Get(':id')`)). The OpenAPI path is `/listings/{id}`.
- "Used in App? = YES" is correct. Call sites:
  - Mobile: `apps\mobile\src\store\productsStore.ts:224` (`getListing`), `apps\mobile\src\screens\profile\ResumeDraft.tsx:39` (`getListing`), `apps\mobile\src\screens\profile\SellerListingDetail.tsx:89` (`getListing`), `apps\mobile\src\screens\profile\SellerListingStatus.tsx:36` (`getListing`), `apps\mobile\src\screens\profile\SellerEditPrice.tsx:61` (`getListing`). The API wrapper is `apps\mobile\src\services\listingsApi.ts:307` (`getListing`).
  - Admin web: `apps\web\src\lib\api.ts:158` (`getListing`), called from `apps\web\src\app\admin\listings\[id]\page.tsx:61` (`getListing`).
  - Seller web: `apps\web\src\lib\sellerApi.ts:438` (`getListing`).
- Usage Note "Flow 3, 18, 26": not verifiable, because I had no flow definitions.
- The Title is the stated requirement, and it conflicts with the code. See the matrix.

## Test design inputs
**Roles and permissions**
- Anonymous, buyer, owner and admin can all call the endpoint (`OptionalJwtAuthGuard`, `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`)). Nothing returns 401 or 403.

**Ownership**
- Owner means `viewer.id === sellerId` (`listings\listings.service.ts:784` (`isOwner`)). Admin means `role === Role.ADMIN`. Both are exempt from the `pending_approval` gate only.

**Resource states**
- Anonymous or other-user viewers: `pending_approval` gives 404. `draft`, `rejected`, `inactive`, `sold`, `reserved`, `active` and `approved` give 200 with `listingStatus` set. A soft-deleted listing gives 404 for everyone.
- Owner and admin: `pending_approval` gives 200. A soft-deleted listing still gives 404.
- The `approved` status appears in the fixtures. I did not check whether it exists as a distinct listing status in the code.

**Validation and error paths**
- Any unknown, malformed or empty id gives 404 `NotFoundException` ("Listing not found"). There is no format validation, so a wrong-format id presumably reaches Prisma as a plain string lookup. I did not verify the error body shape beyond Nest's default.

**Response contract (from `toListingDto`, `listings\listings.service.ts:241-305`)**
- Fields: `id`, `sellerId`, `title`, `description`, `brandId`, `categoryId`, `subcategoryId`, `typeId`, `attributes[]`, `condition`, `priceCents`, `originalPriceCents`, `shippingCents`, `shippingTier`, `size`, `color`, `material`, `era`, `stock`, `currency`, `images[]` (URL strings), `videoUrl`, `tags`, `likeCount`, `commentCount`, `watchersCount`, `ratingAvg`, `reviewCount`, `status` (via `mapStatus`), `listingStatus`, `negotiable`, `minOfferPercent`, `createdAt`, `brand`, `category`, `seller`.
- `offerCount` is deliberately absent (BRI-54). The code comment at `listings\listings.service.ts:284` says so, and a test asserts it (`listings\listings.service.spec.ts:945`).
- The response does not depend on the role, apart from the 404 gate.
- OpenAPI has no response schema, so Schemathesis cannot check the content.

**Business logic**
- The read has no side effects except a cache write. Cache key `listing:<id>` holds a DTO shared across callers, and the gate is re-applied on every request (`listings\listings.service.ts:784-788`). The spec test at `listings\listings.service.spec.ts:999` covers a cache hit.
- Cache staleness after status changes is a risk, per the KB lead above.

**Existing tests**
- `listings\listings.service.spec.ts:956` hides `pending_approval` from an anonymous or buyer viewer.
- `listings\listings.service.spec.ts:965` asserts that `draft`, `rejected` and `inactive` ARE returned to a buyer ("BRI-44 stays as-is").
- `listings\listings.service.spec.ts:974` and `listings\listings.service.spec.ts:980` cover owner and admin seeing `pending_approval`.
- `listings\listings.service.spec.ts:986` returns `sold` and `reserved` to a buyer.
- `listings\listings.service.spec.ts:999` re-applies the gate on a cache hit.
- `listings\listings.repository.spec.ts:940` covers the repository read of a deleted listing ("gone").
- Code comments at `listings\listings.service.ts:50-54` explain the deliberate "reachable page, Buy Now/Make Offer disabled" behaviour for `draft`, `rejected` and `inactive` (BRI-44).
- Mobile's own comment says the same, and mobile treats a 404 as "listing removed" (`apps\mobile\src\store\productsStore.ts:229` (`selectedListingMissing`)).

**Fixtures** (`D:\API_workflow\schemathesis\fixtures.json:3-37`)
- Eight listings, all owned by the QA user account, in these states: draft, pending_approval, approved, active, rejected, inactive, sold, reserved (one id each, see `fixtures.json` `_states`).
- No soft-deleted listing exists on QA (`_readme`), so a removed-listing case needs a fixture to be created.
- Accounts needed: an anonymous caller, a non-owner buyer, the owner (the QA user) and an admin.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code (file:line) | Existing tests | Verdict |
|---|---|---|---|---|---|
| Draft listing visible to a non-owner non-admin | Title: not visible | not specified | returned (200). `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`) gates only `pending_approval` | `listings\listings.service.spec.ts:965` asserts a draft IS returned to a buyer | Conflict |
| Removed (soft-deleted) listing visible to a non-owner non-admin | Title: not visible | not specified | 404 for all. `listings\listings.repository.ts:694` (`NOT_DELETED`) | `listings\listings.repository.spec.ts:940` | Agree for non-owners. Unspecified for owner or admin, who also get 404. |
| `pending_approval` visibility | Title does not mention it (BRI-636 comment says the listing is dark to buyers) | not specified | 404 for non-owner and non-admin. `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`) | `listings\listings.service.spec.ts:956` | Agree with the ticket comment. Unspecified in the sheet. |
| Owner or admin sees the hidden listing | Title: yes | not specified | yes, but only for `pending_approval`. A removed listing is 404 even for them | `listings\listings.service.spec.ts:974`, `listings\listings.service.spec.ts:980` | Conflict for removed listings. Unclear whether the sheet intends the owner or admin to see removed listings. |
| `rejected` and `inactive` visible | Title is silent (a draft or removed listing is named; these are not) | not specified | returned (200) | `listings\listings.service.spec.ts:965` | Unspecified-in-requirement |
| Response schema | none | 200 only, no schema, no 404 | full DTO | n/a | Spec-gap |

Cases with no trustworthy expected result until the product owner clarifies: draft, `rejected` and `inactive` visibility for non-owners. The code and its tests deliberately follow BRI-44, while the Title says draft must be hidden.

## Suggested test scenarios
| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Anonymous reads a draft listing | anon | non-owner | draft id | 404 (per Title). Code returns 200. | body not a listing DTO | Requirement (sheet Title) | Conflict | Business-rule | fixture id; Schemathesis cannot assert without an owner or state oracle |
| 2 | Non-owner buyer reads a draft listing | buyer | non-owner | draft id | 404 per Title. Code returns 200. | as above | Requirement | Conflict | Business-rule | buyer account |
| 3 | Owner reads own draft | owner | owner | draft id | 200 | `listingStatus` is `draft`, `sellerId` equals the owner | Requirement (Title) and code | Confirmed | Response-content | owner token |
| 4 | Admin reads a draft | admin | non-owner | draft id | 200 | `listingStatus` is `draft` | Requirement (Title) and code | Confirmed | Response-content | admin token |
| 5 | Anonymous reads a removed (soft-deleted) listing | anon | non-owner | soft-deleted id | 404 | error body "Listing not found" | Requirement and code | Confirmed | Status-only | new soft-deleted fixture |
| 6 | Owner and admin read a removed listing | owner, admin | owner, non-owner | soft-deleted id | Title implies 200. Code returns 404. | n/a | Requirement | Unclear | Business-rule | soft-deleted fixture |
| 7 | Anonymous or non-owner reads `pending_approval` | anon, buyer | non-owner | pending_approval id | 404 | error body "Listing not found" | Backend code, spec test, ticket comment (BRI-636) | Assumed (not in the sheet) | Business-rule | fixture |
| 8 | Owner and admin read `pending_approval` | owner, admin | owner, non-owner | pending_approval id | 200 | `listingStatus` is `pending_approval` | Backend code, spec test | Assumed | Response-content | owner and admin tokens |
| 9 | Anonymous reads `rejected`, `inactive`, `sold`, `reserved`, `active`, `approved` | anon | non-owner | one id per state | 200 per code. For `rejected` and `inactive` the Title is silent. | `listingStatus` matches the state | Backend code and tests | Assumed | Response-content | fixtures |
| 10 | Unknown, malformed or empty-ish id | anon | n/a | `nonexistent`, very long string, `%00`, unicode, SQL-like text | 404 expected (assumed) | no 5xx, error body shape | QA suggestion | Assumed | Status-only | Schemathesis can run it |
| 11 | Invalid or expired bearer token | anon | n/a | live listing with a bad token | Unclear: 200 vs 401, depending on how `OptionalJwtAuthGuard` handles it. I did not read the guard. | n/a | QA suggestion | Unclear | Security | token manipulation |
| 12 | Cache staleness: status change then read | owner then anon | owner | live listing changed to `pending_approval` or `draft` | the anonymous read reflects the change immediately (assumed) | status and visibility updated | Documentation (qa-knowledge) | Assumed | Business-rule | owner token, status-change endpoint |
| 13 | Response does not leak offer count | any | any | live listing | 200 | no `offerCount` field, no `viewsCount` | Backend test (`listings\listings.service.spec.ts:945`) and ticket comment BRI-54 | Assumed | Contract | n/a |
| 14 | Contract: response schema | any | any | live listing | 200 | OpenAPI has no schema, so only status conformance is possible | OpenAPI | Spec-gap | Contract | add a response schema |
| 15 | Unexpected query params or body on GET | any | any | `?status=draft`, `?viewer=admin`, `?role=ADMIN` | same as without them | no behaviour change | QA suggestion | Assumed | Security | n/a |
| 16 | Admin web detail page for a draft or removed listing | admin | non-owner | admin web page | page loads for a draft. For removed it receives a 404. | n/a | Backend code | Unclear | Business-rule | admin UI session |

## Summary: 0 unused request items, 0 unused response fields (per-field A3 partial, not complete), 2 dead files/branches (none confirmed; `currency` constant and `watchersCount` duplicating `likeCount` are the only B4 items), 2 conflicts (draft visibility, removed listing for owner/admin), 16 suggested scenarios
