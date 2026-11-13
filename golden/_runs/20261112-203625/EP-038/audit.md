# Endpoint #EP-038 - GET /listings/:id

Paths below are relative to the folder named in each heading.

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `listings\listings.controller.ts:374` (`@Get(':id')`), guard `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`), handler `listings\listings.controller.ts:376` (`findById`).
- Guard: `auth\guards\optional-jwt-auth.guard.ts:14` (`handleRequest`). It never throws. A missing or invalid token gives `req.user` undefined, so there is never a 401.
- Service: `listings\listings.service.ts:769` (`findById`). It uses a cache and a per-request visibility gate at `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`). The constant is defined at `listings\listings.service.ts:60`.
- Repository: `listings\listings.repository.ts:692` (`findById`) filters on `listings\listings.repository.ts:694` (`NOT_DELETED`). The constant is `listings\listing.constants.ts:68` (`NOT_DELETED`, `deletedAt: null`).
- Serializer: `listings\listings.service.ts:240` (`toListingDto`).
- Tests: `listings\listings.service.spec.ts:956`, `:965`, `:974`, `:980`, `:986`; `listings\listings.repository.spec.ts:940`.

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\listingsApi.ts:307` (`getListing`).
- Callers:
  - `store\productsStore.ts:224` (buyer and guest detail, no token).
  - `screens\profile\SellerListingStatus.tsx:36` (with token).
  - `screens\profile\SellerListingDetail.tsx:89` (with token).
  - `screens\profile\SellerEditPrice.tsx:61` (with token).
  - `screens\profile\ResumeDraft.tsx:39` (no token).

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- `lib\api.ts:158` (admin `getListing`), called from `app\admin\listings\[id]\page.tsx:61`.
- `lib\sellerApi.ts:438` (seller `getListing`), called from `app\seller\listings\[id]\edit\page.tsx:84`.
- `lib\shareLinks.ts:137` (unauthenticated read for share metadata).

## Declared contract
- **Path param:** `id`, a string with no validation pipe at `listings\listings.controller.ts:376`. OpenAPI declares `id` as a required string path param, no format (`schemathesis\spec\openapi.pretty.json:1554-1562`).
- **Headers:** an optional `Authorization: Bearer` header is read by the guard. OpenAPI declares no security scheme and no header for this operation.
- **Body and query:** none.
- **OpenAPI responses:** only `200` with an empty description and no schema (`schemathesis\spec\openapi.pretty.json:1564-1568`). `404` is undocumented and no response schema is declared.
- **Code statuses:**
  - `200`: the DTO.
  - `404 'Listing not found'` (`listings\listings.service.ts:775`): unknown id, or `deletedAt` set.
  - `404 'Listing not found'` (`listings\listings.service.ts:787`): the listing is `pending_approval` and the viewer is neither owner nor admin.
  - No 400, 401 or 403 path. A 5xx is possible only from an infrastructure failure.
- **Response (`toListingDto`):** `id`, `sellerId`, `title`, `description`, `brandId`, `categoryId`, `subcategoryId`, `typeId`, `attributes[]`, `condition`, `priceCents`, `originalPriceCents`, `shippingCents`, `shippingTier`, `size`, `color`, `material`, `era`, `stock`, `currency`, `images[]`, `videoUrl`, `tags`, `likeCount`, `commentCount`, `watchersCount`, `ratingAvg`, `reviewCount`, `status`, `listingStatus`, `negotiable`, `minOfferPercent`, `createdAt`, `brand`, `category`, `seller` (`listings\listings.service.ts:241-305`). There is deliberately no `offerCount` (`listings\listings.service.ts:284`).
- The response is identical for every viewer. There is no role-dependent field. Only the status gate depends on the viewer.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | The sheet title requires "draft or removed" to be hidden from non-owner/non-admin. The code hides `pending_approval` only. `draft`, `rejected` and `inactive` are returned to anyone; deleted (`deletedAt`) listings are 404 for everyone, including owner and admin. | response/branch | Requirement vs code mismatch (not B1-B5) | `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`), `listings\listings.service.spec.ts:965` (asserts draft/rejected/inactive are returned to a buyer) | all roles | high |
| 2 | Mobile `productsStore.fetchListing` calls `getListing(id)` with no token. An owner or admin opening their own `pending_approval` listing through the buyer detail screen gets 404. | app call | Behaviour lead (not a B/A category) | `store\productsStore.ts:224` (`getListing`), `services\listingsApi.ts:304-308` (comment says the token must be passed) | mobile buyer detail | med (I did not trace which screens route there) |
| 3 | `viewer.id === result.sellerId` is evaluated with `viewer` undefined for guests. This is safe because `undefined === sellerId` is false. | branch | none | `listings\listings.service.ts:784` (`isOwner`) | backend | high |
| 4 | Cached DTO `listing:<id>` has no TTL override and is shared across callers. Staleness after a status change is a risk if any write path skips invalidation. | file/response | none | `listings\listings.service.ts:770` (`cacheKey`) | backend | med |
| 5 | A3, mobile. Mobile `ListingDto` extends `Product` and declares `attributes`, `listingStatus`, `watchersCount`, `negotiable`, `seller`, `brand` and `category` (`services\listingsApi.ts:54-78`). I did not open `Product`. I did not trace per-field screen reads, so `shippingTier`, `minOfferPercent`, `era`, `material`, `typeId`, `brandId` and `commentCount` are unverified. | response | A3 | `services\listingsApi.ts:54` (`ListingDto`) | mobile | low |
| 6 | A3, web. The web types `AdminListingDetail` and `ListingDetail` were not opened, so per-field use is unverified. | response | A3 | `lib\api.ts:158` (`getListing`), `lib\sellerApi.ts:438` (`getListing`) | web | low |
| 7 | B1/B2: none found. The only input is `id` and the optional token, and both affect the outcome. B3: no dead branch. B5: none. B4: `currency` is the constant `'USD'` (`listings\listings.service.ts:274`, `currency`). | - | B4 (minor) | `listings\listings.service.ts:274` | backend | high |
| 8 | A1/A2: no unsent request fields exist. The app sends only the optional token. | - | A1/A2 | `services\listingsApi.ts:308` (`getListing`) | mobile | high |

## Looks unused but keep
- The optional token is not used for authorization of a 401. It is needed so the owner or an admin can see a `pending_approval` listing (BRI-636, `listings\listings.controller.ts:369-372`).
- `sellerId` in the DTO is needed server-side for the owner check (`listings\listings.service.ts:784`).

## Could not verify
- Whether QA fixtures behave as labelled in `D:\API_workflow\schemathesis\fixtures.json`. This is a live-environment question; I only read the file.
- Whether a deleted listing's 404 applies to an admin. The code is the only evidence, and no requirement source was found for it.
- Mobile `Product` type and per-screen field reads (A3).
- The web `AdminListingDetail` and `ListingDetail` field reads (A3).
- The cache TTL default (not found in the files read).
- Whether any requirement source beyond the sheet title (full-spec.md, docs\) defines "removed". I did not search them separately. Only code comments and KB were consulted.

## Knowledge base cross-check
- I consulted `qa-knowledge\modules\listings.md:122-127` (the `GET /listings/:id` section), `qa-knowledge\flows.md:43` (Flow 3, listing creation, review and go-live) and `qa-knowledge\test-scenarios.md:104` (TS-LISTINGS-007).
- Confirmed in code:
  - `OptionalJwtAuthGuard` (`listings\listings.controller.ts:375`).
  - The shared cache key (`listings\listings.service.ts:770`).
  - The owner/admin gate (`listings\listings.service.ts:786`).
  - No `offerCount` (`listings\listings.service.ts:284`).
- The KB frontend claims about `listingsApi.getListing` and the token requirement (BRI-781) are confirmed at `services\listingsApi.ts:304-308`.
- The KB describes `pending_approval` as the only status hidden. I confirmed this at `listings\listings.service.ts:60`.
- Not covered by the KB: soft-deleted behaviour on this endpoint and the productsStore no-token call (finding 2).
- Other KB lines mentioning Flow 18 and Flow 26 were not checked.

## Sheet check
- **Method and path:** match. The code is `@Get(':id')` under the listings controller, and OpenAPI has `/listings/{id}` GET.
- **"Used in App?" = YES:** correct. Mobile call sites are `services\listingsApi.ts:307` via `store\productsStore.ts:224`, `screens\profile\SellerListingStatus.tsx:36`, `screens\profile\SellerListingDetail.tsx:89`, `screens\profile\SellerEditPrice.tsx:61` and `screens\profile\ResumeDraft.tsx:39`. Web call sites are `lib\api.ts:158`, `lib\sellerApi.ts:438` and `lib\shareLinks.ts:137`.
- **Usage Note "Flow 3, 18, 26":** Flow 3 (creation, review, go-live) plausibly matches. The seller review and edit screens and the admin review fit. I did not verify Flows 18 and 26. The note omits the buyer and guest detail flow, the web admin detail page and the web seller edit page.
- **Title vs behaviour (mismatch):** the title says draft or removed listings are not visible to non-owner users. The code and its tests deliberately return draft, rejected and inactive to everyone (`listings\listings.service.ts:48-60`, `listings\listings.service.spec.ts:961-972`). Only `pending_approval` is hidden. Soft-deleted listings are hidden from everyone.

## Test design inputs
- **Roles:**
  - Anon, buyer, seller-owner and admin may all call it; there is no 401 or 403 (`auth\guards\optional-jwt-auth.guard.ts:14`).
  - Role only changes visibility of `pending_approval` listings (`listings\listings.service.ts:784-788`).
  - Admin is checked as `Role.ADMIN`.
- **Ownership:** decided by `viewer.id === sellerId` (`listings\listings.service.ts:784`). An owner who is not admin sees their own `pending_approval` listing.
- **Resource states and who sees what:**

| State | Anon / buyer | Owner | Admin |
|---|---|---|---|
| `draft`, `rejected`, `inactive` | 200 | 200 | 200 |
| `pending_approval` | 404 | 200 | 200 |
| `approved`, `active`, `sold`, `reserved` | 200 | 200 | 200 |
| soft-deleted | 404 | 404 (deletedAt filter) | 404 (deletedAt filter) |

  - Evidence: `listings\listings.service.ts:786`, `listings\listings.repository.ts:694`, `listings\listings.service.spec.ts:986` (sold/reserved).
  - The "soft-deleted: 404 for every role" row is `listings\listings.repository.ts:694`. For an admin I have only the code, so it is Assumed.
- **Validation and errors:** there is no id format validation, so any string gives 404 for an unknown id. The 404 body is the Nest default `{statusCode, message:'Listing not found', error:'Not Found'}`.
- **Response contract:** see Declared contract. There is no response schema in OpenAPI, so Schemathesis can check only status codes and conformance of undocumented responses. No field depends on role.
- **Business logic and side effects:** the response is cached per id with no TTL override seen (`listings\listings.service.ts:777`). The gate runs after the cache read. The listing can appear stale until `ListingsService.invalidateCache` runs; this is per the KB, and I did not re-verify the callers.
- **Existing tests:** `listings\listings.service.spec.ts:956` (pending_approval hidden from anon), `:965` (draft/rejected/inactive returned), `:974` (own seller sees pending), `:980` (admin sees pending), `:986` (sold/reserved shown), `:945` (no offerCount); `listings\listings.repository.spec.ts:940` (a deleted listing reads as gone). There is no e2e or controller test. No test covers a non-owner USER with a different id on `pending_approval`.
- **Fixtures:** from `D:\API_workflow\schemathesis\fixtures.json:4-11` (`_states`): ids for draft, pending_approval, approved, active, rejected, inactive, sold and reserved, all owned by the ST_USER account (`_owners`). The README says no soft-deleted listing exists yet. Still needed: a soft-deleted listing, a non-owner buyer token, an admin token, and a non-owner seller token.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code (file:line) | Existing tests | Verdict |
|---|---|---|---|---|---|
| draft listing visible to non-owner | Title: not visible | no statement | returned (`listings\listings.service.ts:60`) | spec asserts visible (`listings\listings.service.spec.ts:965`) | Conflict: the title and the code and its tests disagree; the code cites BRI-44 as a settled decision. Needs clarification. |
| "removed" (soft-deleted) visible to owner/admin | Title: owner/admin may see it | none | 404 for all (`listings\listings.repository.ts:694`) | `listings\listings.repository.spec.ts:940` | Conflict: unclear whether "removed" means deleted, rejected or inactive. |
| rejected / inactive visible to non-owner | Title implies "removed" is hidden | none | returned (`listings\listings.service.ts:60`) | `listings\listings.service.spec.ts:965` | Conflict (depends on the meaning of "removed") |
| pending_approval hidden from non-owner/non-admin | Not in the sheet title; BRI-636 and BRI-46 named in code comment | none | 404 (`listings\listings.service.ts:786`) | `listings\listings.service.spec.ts:956` | Agree with the ticket. The sheet title does not mention it. |
| pending_approval visible to owner/admin | BRI-636 | none | allowed (`listings\listings.service.ts:784-785`) | `listings\listings.service.spec.ts:974`, `:980` | Agree |
| 404 documented | none | only 200 documented | 404 thrown (`listings\listings.service.ts:775`) | none | Spec-gap |
| guest allowed | BRI-636 comment | no security declared | guard never rejects (`auth\guards\optional-jwt-auth.guard.ts:14`) | `auth\guards\optional-jwt-auth.guard.spec.ts:3` | Agree |
| response schema | none | absent | `listings\listings.service.ts:241` | none | Spec-gap |

## Suggested test scenarios
All statuses and assertions below that come from code behaviour are labelled by their source. Where the sheet title conflicts, the case is Conflict.

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | pending_approval listing, anon | anon | n/a | `pending_approval` id | 404 | message `Listing not found` | Requirement (BRI-636 in code comment) | Confirmed | Business-rule | Fixture id; Schemathesis ok |
| 2 | pending_approval listing, non-owner buyer | buyer | non-owner | same | 404 | same | BRI-636 | Confirmed | Security | buyer token |
| 3 | pending_approval listing, owner | seller | owner | same | 200 | `listingStatus` is `pending_approval`; `sellerId` equals the owner | BRI-636 | Confirmed | Business-rule | owner token |
| 4 | pending_approval, admin | admin | non-owner | same | 200 | `listingStatus` is `pending_approval` | BRI-636 | Confirmed | Business-rule | admin token |
| 5 | draft listing, anon | anon | non-owner | `draft` id | Sheet title says hidden; code returns 200 | n/a until clarified | Requirement vs Backend code | Conflict | Business-rule | clarification |
| 6 | draft listing, non-owner buyer | buyer | non-owner | `draft` id | same as 5 | same | same | Conflict | Security | clarification |
| 7 | rejected and inactive, anon | anon | non-owner | each id | Conflict (code: 200) | `listingStatus` equals the state | Requirement vs code | Conflict | Business-rule | clarification |
| 8 | draft, owner | seller | owner | `draft` id | 200 | `listingStatus` is `draft` | Title (owner may view) and code agree | Confirmed | Response-content | owner token |
| 9 | draft, admin | admin | non-owner | `draft` id | 200 | same | Title and code agree | Confirmed | Response-content | admin token |
| 10 | soft-deleted listing (via `DELETE /listings/:id`), anon, owner and admin | each | owner or non-owner | deleted id | Anon: 404 (code and title agree). Owner/admin: title implies visible, code 404 | message `Listing not found` | Title vs code | Conflict for owner/admin | Business-rule | a soft-deleted fixture (none on QA) |
| 11 | sold and reserved, anon | anon | non-owner | each id | 200 | `listingStatus` matches | Existing test (`listings\listings.service.spec.ts:986`) | Assumed | Response-content | fixtures |
| 12 | approved/active listing, anon | anon | non-owner | each id | 200 | all `toListingDto` fields present; no `offerCount`; `currency` is `USD`; `images` is an array of strings | Backend code | Assumed | Contract | fixtures |
| 13 | unknown id (nonexistent string cuid) | anon | n/a | nonexistent id | 404 | message `Listing not found` | Backend code | Assumed | Status-only | Schemathesis ok |
| 14 | odd id: very long string, SQL-like, unicode, path chars | anon | n/a | such strings | 404, not 5xx | no stack trace in the body | QA suggestion | Assumed | Security | Schemathesis ok |
| 15 | invalid or expired bearer token | anon | n/a | `pending_approval` id, bad token | 404 (treated as a guest); not 401 | n/a | Backend code (guard `handleRequest`) | Assumed | Security | token |
| 16 | owner who is a non-admin seller reading another seller's `pending_approval` listing | seller | non-owner | same | 404 | n/a | BRI-636 | Confirmed | Security | second seller token |
| 17 | status change then read (cache staleness): publish, read, pause, read again | owner | owner | active then inactive/draft | the second read reflects the new `listingStatus` right away | `listingStatus` updated | QA suggestion | Assumed | Business-rule | other method (seller flow plus timing) |
| 18 | mobile buyer detail flow for an owner/admin of a `pending_approval` listing (no token sent by `productsStore.fetchListing`) | mobile UI | owner | pending id | 404 expected from the no-token call (observation) | n/a | Backend code vs `store\productsStore.ts:224` | Unclear | Business-rule | manual/UI |
| 19 | unexpected query params (`?status=draft`) | anon | n/a | `active` id | 200, param ignored | same as scenario 12 | QA suggestion | Assumed | Contract | Schemathesis ok |
| 20 | admin web page (`app\admin\listings\[id]\page.tsx:61`) loads for a pending listing | admin | non-owner | pending id | 200 | detail rendered | QA suggestion | Assumed | Response-content | manual (the web client) |

## Summary: 0 unused request items, 0 confirmed unused response fields (A3 not fully assessed; per-field reads unverified in both clients), 0 dead files/branches, 3 conflicts (draft, rejected/inactive, soft-deleted owner/admin visibility vs the sheet title), 20 suggested scenarios
