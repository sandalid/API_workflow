# Endpoint #38 - GET /listings/:id

Headline: the sheet title says a draft or removed listing is hidden from everyone except its owner or an admin. The code only hides `pending_approval` that way. `draft`, `rejected` and `inactive` are returned to any caller, including guests, and the unit tests assert this on purpose. Soft-deleted listings are hidden from everyone with a 404, owner and admin included. This is a Conflict between the requirement and the code.

## Files involved

### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route `listings\listings.controller.ts:374` (`@Get(':id')`).
  - Guard `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`).
  - Handler `listings\listings.controller.ts:376` (`findById`).
  - The `@Get(':id')` route is declared after `mine`, `:id/open-offers` and `:id/views`, so those literal routes are not captured by `:id`.
- Guard `auth\guards\optional-jwt-auth.guard.ts:14` (`handleRequest`). It never throws, so a bad or missing token leaves `req.user` undefined.
- Service `listings\listings.service.ts:769` (`findById`).
  - Cache key `listings\listings.service.ts:770` (`cacheKey`).
  - Gate `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`).
  - Constant `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`).
- Serializer `listings\listings.service.ts:240` (`toListingDto`).
- Repository `listings\listings.repository.ts:692` (`findById`). It uses `findFirst` with `NOT_DELETED` (line 694), so soft-deleted rows return null and the service answers 404.
- Cache invalidation: `listings\listings.service.ts:1230` (`listing:${listingId}`) and other `del` calls at 1385, 1403, 1431, 1609 and 2161.

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\listingsApi.ts:307` (`getListing`).
- `store\productsStore.ts:220` (`fetchListing`).
- `utils\listingState.ts:44` (`isListingUnavailable`).

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- `lib\api.ts:157` (`getListing`, admin).
- `lib\sellerApi.ts:437` (`getListing`, seller).

## Declared contract

**Backend code**
- Path param `id` is a plain string with no pipe or validation (`listings\listings.controller.ts:376` (`@Param('id')`)).
- No query params, no body.
- The `Authorization` header is read optionally through the guard.
- Responses:
  - 200 with the `toListingDto` object.
  - 404 `Listing not found` in two cases: no row or soft-deleted (`listings\listings.service.ts:775` (`NotFoundException`)), or `pending_approval` for a viewer who is neither owner nor admin (`listings\listings.service.ts:787`).
  - Any other status is not raised by the code. An unexpected failure would be a 500.
  - There is no 401 or 403 path.
- 200 fields (`listings\listings.service.ts:241-305`):
  - Ids and text: `id`, `sellerId`, `title`, `description`, `brandId`, `categoryId`, `subcategoryId`, `typeId`.
  - `attributes[{name,slug,value}]`.
  - Condition and price: `condition`, `priceCents`, `originalPriceCents`, `shippingCents`, `shippingTier`.
  - Item details: `size`, `color`, `material`, `era`, `stock`.
  - `currency` (constant `'USD'`).
  - Media and tags: `images[]`, `videoUrl`, `tags`.
  - Counts and ratings: `likeCount`, `commentCount`, `watchersCount` (equal to `likeCount`), `ratingAvg`, `reviewCount`.
  - Status and offers: `status` (derived through `mapStatus` as available, sold or reserved), `listingStatus` (the raw status), `negotiable`, `minOfferPercent`.
  - `createdAt`, `brand`, `category`, `seller` (from `mapSeller`, including `lastActiveAt`).
- No `offerCount` or views count by design (`listings\listings.service.ts:284`).

**OpenAPI** (`schemathesis\spec\openapi.pretty.json:1551-1572`)
- `ListingsController_findById`, summary "Get one listing by id".
- Path param `id` is a required string.
- Only a `200` response with an empty description and no schema.
- No 404 and no security requirement are documented.

## Findings

| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | Status-based visibility is `pending_approval` only. `draft`, `rejected` and `inactive` are returned to every caller. | branch | Not B1-B5 (behaviour conflict with the sheet title) | `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`); `listings\listings.service.spec.ts:965` (`it.each(['draft', 'rejected', 'inactive']`) | backend | high |
| 2 | Soft-deleted listings 404 for everyone, owner and admin included. The sheet says an owner or admin should see "removed" ones, which this contradicts. | branch | Conflict | `listings\listings.repository.ts:694` (`NOT_DELETED`) | backend | high |
| 3 | Mobile only calls it "removed" on a 404. Draft is handled client-side by `isListingUnavailable`, so a draft still renders for buyers with the CTAs disabled. | response | A4 | `utils\listingState.ts:44` (`isListingUnavailable`) | mobile buyer | med |
| 4 | `watchersCount` always equals `likeCount`. | response | B4 (derived, not constant) | `listings\listings.service.ts:283` (`watchersCount`) | backend | high |
| 5 | `currency` is a constant `'USD'`. | response | B4 | `listings\listings.service.ts:274` (`currency`) | backend | high |
| 6 | Mobile never sends a token from the buyer detail path (`fetchListing` calls `getListing(id)` with no token). A seller or admin opening their own `pending_approval` listing through `ProductDetail` or the offer threads would get 404. | A1 | A1 | `store\productsStore.ts:224` (`getListing`), `services\listingsApi.ts:307` (`getListing`) | mobile | high |
| 7 | Mobile and web read subsets of the response (A3 below). | response | A3 | see table below | mobile and web | med |
| 8 | The 200 response has no schema and 404 is undocumented in the spec. | spec | Spec-gap | `schemathesis\spec\openapi.pretty.json:1564` (`"responses"`) | spec | high |

### A3 response fields, per client

**Mobile**
- Types: `ListingDto` and `Product` at `types\domain.ts:50` (`Product`), `services\listingsApi.ts:54` (`ListingDto`).
- Typed and used by the detail flow (type declared; screen reading checked only for the fields listed under "Read by"):
  - `id`, `sellerId`, `title`, `description`, prices, `images`, `tags`, `likeCount`, `commentCount`, `status`, `listingStatus`, `negotiable`, `minOfferPercent`, `seller`, `brand`, `category`.
  - `videoUrl`: read in `screens\home\ProductDetail.tsx:429`.
  - `attributes`: read in `screens\home\ProductDetail.tsx:1035`.
  - `listingStatus`: read through `isListingUnavailable` at `screens\home\ProductDetail.tsx:367`.
- Not found in `ProductDetail.tsx`: `ratingAvg` and `reviewCount` (the only `reviewCount` hits in mobile are on other types), `shippingTier`, `material`, `era`, `watchersCount`, `subcategoryId` and `typeId`.
  - Not found anywhere in mobile screens: `ratingAvg`, and listing-level `reviewCount` (`types\domain.ts:15` is a user type).
  - `watchersCount`, `shippingTier`, `material`, `era`, `subcategoryId` and `typeId` are declared as types (`services\listingsApi.ts:62`, `types\domain.ts:84`). I did not exhaustively trace the seller screens (`SellerListingDetail`, `SellerEditPrice`, `ResumeDraft`, `SellerListingStatus`), so seller-flow reads of these are unverified.
  - `lastActiveAt` is typed (`services\listingsApi.ts:18`). I did not verify a screen reads it.

**Web admin** (`AdminListingDetail`, `lib\types.ts:280`)
- Reads a subset of fields.
- The type omits `sellerId`, `brandId`, `categoryId`, `subcategoryId`, `typeId`, `attributes`, `material`, `era`, `shippingTier`, `videoUrl`, `likeCount`, `commentCount`, `watchersCount`, `ratingAvg`, `reviewCount`, `status`, `currency`, `minOfferPercent`. No code in the admin type or page consumes these.

**Web seller** (`ListingDetail`, `lib\sellerApi.ts:104`)
- Reads subset: `id`, `title`, `description`, prices, `stock`, `condition`, `size`, `color`, `tags`, `images`, `brandId`, `categoryId`, `negotiable`, `minOfferPercent`, `listingStatus`, `brand`, `category`.
- Other fields are untyped and unread by the seller edit page.

## Looks unused but keep
- `listingStatus` is the field that lets mobile show draft, paused or pending states, since `status` flattens them to `available` (`listings\listings.service.ts:234`, `mapStatus`).
- `sellerId` supports the owner check (`listings\listings.service.ts:784`, `isOwner`). It stays in the cached DTO so the gate can run on a cache hit.

## Could not verify
- Whether seller or buyer screens read `shippingTier`, `material`, `era` and `watchersCount`. I grepped `ProductDetail.tsx` only and did not trace the seller screens.
- Real behaviour of a draft, or of a deleted listing for an owner or admin. Code reading only, nothing executed.
- Whether the gate in `findById` is hit for cached values where the cache is stale across seller or status changes. Invalidation calls exist (see Files) but I did not trace every status-changing path.
- Existing e2e coverage of this route: the grep for `get('/listings/<id>')` in `apps\api\test` found none.

## Sheet check
- Method and path: Matches (`listings\listings.controller.ts:374`).
- "Used in App? YES": Matches. Call sites below.
- Title: Mismatch with the code.
  - It states that a draft or removed listing is not visible to anyone but the owner or an admin.
  - Code and unit tests show only `pending_approval` is gated that way.
  - `draft` is public.
  - A soft-deleted listing 404s for the owner and admin too.
- Usage note "Flow 3, 18, 26": I have no flow definitions, so I cannot confirm that mapping.

### Call sites
**Mobile**
- `store\productsStore.ts:224` (`getListing`), via `fetchListing` at `store\productsStore.ts:220`. `fetchListing` is called from:
  - `screens\home\ProductDetail.tsx:259` and `:278` (`fetchListing`).
  - `screens\modals\MakeOffer.tsx:93` (`fetchListing`).
  - `screens\inbox\OfferThread.tsx:85` (`fetchListing`).
  - `screens\seller\offers\SellerOfferDetail.tsx:85` (`fetchListing`).
- Direct calls with a token:
  - `screens\profile\SellerListingStatus.tsx:36` (`getListing`).
  - `screens\profile\SellerListingDetail.tsx:89` (`getListing`).
  - `screens\profile\SellerEditPrice.tsx:61` (`getListing`).
- Direct call without a token: `screens\profile\ResumeDraft.tsx:39` (`getListing`). Note that a draft opened through this call carries no token, so a draft listing is fetched as a guest. This only works because drafts are not hidden by the gate.

**Web admin**
- `lib\api.ts:157` (`getListing`), called from `app\admin\listings\[id]\page.tsx:61` (`adminApi.getListing`).

**Web seller**
- `lib\sellerApi.ts:437` (`getListing`), called from `app\seller\listings\[id]\edit\page.tsx:84` (`sellerApi.getListing`).

**Docs**
- `full-spec.md:322` lists the route against `ProductDetail.tsx`.

## Test design inputs

### Roles and permissions
- Anonymous, buyer, seller and admin may all call it.
- The guard is `OptionalJwtAuthGuard` (`listings\listings.controller.ts:375`). There is no 401 or 403 path.
- An invalid token behaves as anonymous (`auth\guards\optional-jwt-auth.guard.ts:15`).

### Ownership
- Owner means `viewer.id === result.sellerId` (`listings\listings.service.ts:784`).
- Admin means `viewer.role === Role.ADMIN` (`listings\listings.service.ts:785`).
- Only `pending_approval` uses these two checks. For every other status, owner status makes no difference.

### Resource states (as coded)

| State | Guest/buyer | Owner | Admin |
|---|---|---|---|
| `active` / `approved` | 200 | 200 | 200 |
| `sold` / `reserved` | 200 | 200 | 200 |
| `draft` / `rejected` / `inactive` | 200 | 200 | 200 |
| `pending_approval` | 404 | 200 | 200 |
| soft-deleted | 404 | 404 | 404 |
| unknown id | 404 | 404 | 404 |

The first four rows are code behaviour, not requirement. The sheet requires only draft and removed to be hidden. The "soft-deleted" row conflicts with the sheet's "removed ... owner or admin".

### Validation and error paths
- 404 body is Nest's standard `{statusCode: 404, message: 'Listing not found', error: 'Not Found'}`.
- `id` has no format validation. A malformed id is just a lookup miss, 404.
- No 400.

### Response contract
- Fields listed above. `status` and `listingStatus` both appear. `listingStatus` carries the raw lifecycle state.
- The DTO is the same for every role (it is cached and shared), so no field is role-dependent.
- The OpenAPI spec declares no schema.

### Business logic and side effects
- Read-only except for the shared `listing:<id>` cache entry set on a miss (`listings\listings.service.ts:777`).
- The visibility gate runs per request, even on a cache hit.
- Cache is deleted on update, status change and delete (see Files).

### Existing tests and docs
- `listings\listings.service.spec.ts:956` (`hides a pending_approval listing from an anonymous/buyer viewer`).
- `listings\listings.service.spec.ts:965` (`still returns a %s listing to a buyer`) for `draft`, `rejected` and `inactive`.
- `listings\listings.service.spec.ts:974` (owner sees `pending_approval`).
- `listings\listings.service.spec.ts:980` (admin sees `pending_approval`).
- `listings\listings.service.spec.ts:986` (`sold` and `reserved` stay visible).
- `listings\listings.service.spec.ts:999` (gate re-applied on a cache hit).
- `listings\listings.service.spec.ts:920` (404 when the repository returns null).
- Mobile: `services\__tests__\listingsApi.test.ts:131` (URL `/listings/l-1`).
- No e2e coverage found. No `full-spec.md` passage describing draft or removed visibility rules was found. Code comments cite BRI-636 and BRI-44 (`listings\listings.service.ts:48`).

### Fixtures needed
- Listings in each status: `draft`, `pending_approval`, `rejected`, `inactive`, `active`, `sold`, `reserved`, plus one soft-deleted.
- Owner seller account, non-owner buyer account, another seller, and an admin account.
- A token that is expired or invalid.

## Source agreement matrix

| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| Draft listing hidden from non-owner | Hidden (sheet title) | Silent | Not hidden (`listings\listings.service.ts:786`) | Asserts visible (`listings\listings.service.spec.ts:965`) | Conflict |
| Draft visible to owner or admin | Visible | Silent | Visible (as for everyone) | Not tested | Conflict, only through item above |
| Removed (soft-deleted) hidden from others | Hidden | Silent | 404 (`listings\listings.repository.ts:694`) | Not seen | Agree |
| Removed visible to owner or admin | Visible | Silent | 404 for all | Not seen | Conflict |
| `pending_approval` hidden except owner or admin | Not in sheet title | Silent | Gated (`listings\listings.service.ts:786`) | Yes (`:956`) | Unspecified-in-requirement |
| `rejected`, `inactive` visibility | Not in sheet title | Silent | Public | Asserted public | Unspecified-in-requirement |
| Guests may call without token | Not stated | No security declared | Allowed (`listings\listings.controller.ts:375`) | Not tested | Spec-gap |
| 404 documented | n/a | Absent (`schemathesis\spec\openapi.pretty.json:1564`) | 404 returned | Yes | Spec-gap |
| Response schema | n/a | None | `toListingDto` | Partial | Spec-gap |

Conflicts: any test case for "draft hidden from a buyer" or for "removed visible to owner or admin" has no trustworthy expected result until the requirement is clarified.

## Suggested test scenarios

| # | Scenario | Role | Ownership | State/Input | Expected | Response assertions | Source | Req status | Level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Guest reads an active listing | anon | n/a | active | 200 | `id` matches, `listingStatus` is active or approved | QA suggestion | Assumed | Response-content | active id (Schemathesis can only check status/conformance, no schema in spec) |
| 2 | Guest reads a draft listing | anon | non-owner | draft | Sheet says 404, code gives 200 | n/a | Requirement vs code | Conflict | Business-rule | draft fixture, manual |
| 3 | Owner reads own draft | seller | owner | draft | 200 | `listingStatus` is draft | Requirement | Confirmed (title) | Business-rule | draft fixture, owner token |
| 4 | Admin reads draft | admin | n/a | draft | 200 | same | Requirement | Confirmed (title) | Business-rule | admin token |
| 5 | Other buyer reads draft | buyer | non-owner | draft | Sheet 404, code 200 | n/a | Requirement vs code | Conflict | Security | fixture |
| 6 | Guest reads soft-deleted listing | anon | n/a | deleted | 404 | Nest error body | Requirement and code | Confirmed | Business-rule | deleted fixture |
| 7 | Owner or admin reads soft-deleted listing | seller, admin | owner | deleted | Sheet implies 200, code 404 | n/a | Requirement vs code | Conflict | Business-rule | deleted fixture |
| 8 | Guest reads `pending_approval` | anon | non-owner | pending | 404 | message `Listing not found` | Backend code, tests | Assumed (not in sheet) | Business-rule | fixture |
| 9 | Owner and admin read `pending_approval` | seller, admin | owner | pending | 200 | `listingStatus` pending_approval | Backend code | Assumed | Business-rule | fixtures |
| 10 | Cache hit after status change to pending | anon | n/a | read active, then raise price over threshold, read again | 404 on second read | n/a | Backend code | Assumed | Business-rule | seller flow and fixture |
| 11 | Unknown id | anon | n/a | `does-not-exist` | 404 | error body | Backend code | Assumed | Status-only | none (Schemathesis ok) |
| 12 | Malformed or oddly encoded id (SQL-ish, very long, unicode) | anon | n/a | id odd values | 404, no 500 | n/a | QA suggestion | Assumed | Security | Schemathesis ok |
| 13 | Invalid or expired token on a public listing | anon with bad token | n/a | active | 200, not 401 | n/a | Backend code | Assumed | Business-rule | bad token |
| 14 | Non-owner seller with token reads draft | seller | non-owner | draft | Sheet 404, code 200 | n/a | Requirement vs code | Conflict | Security | fixture |
| 15 | Response must not contain `offerCount` or views | any | n/a | active | 200 | no `offerCount` key | Test, code | Assumed | Contract | active id |
| 16 | Unexpected query param (`?status=draft`) | anon | n/a | active | 200, ignored | n/a | QA suggestion | Assumed | Status-only | Schemathesis ok |

## Summary: 1 unused request item (the token mobile does not send on the buyer path), 0 unused response fields confirmed unanimously (several unread per client, see A3), 0 dead files, 4 conflicts (draft hidden from non-owner, draft visible to owner or admin, removed visible to owner or admin, and the test asserting draft is visible), 16 suggested scenarios
