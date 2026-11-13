# Endpoint #EP-038 - GET /listings/:id

Scope note: the app source was available and searched in both clients. I could not read the GET /listings/{id} operation in `schemathesis\spec\openapi.json`. The file is minified on one line and the search tool omits long lines. All OpenAPI claims below are therefore not verified, except that the path key exists.

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `listings\listings.controller.ts:374` (`@Get(':id')`). The guard is at `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`). The handler is at `listings\listings.controller.ts:376` (`findById`).
- Guard: `auth\guards\optional-jwt-auth.guard.ts:13` (`OptionalJwtAuthGuard`). It never rejects, so an invalid or missing token leaves `req.user` undefined (`auth\guards\optional-jwt-auth.guard.ts:14`, `handleRequest`).
- Service: `listings\listings.service.ts:769` (`findById`). The visibility gate is at `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`). The constant is defined at `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`).
- DTO mapper: `listings\listings.service.ts:240` (`toListingDto`). It includes `sellerId` (`listings\listings.service.ts:243`, `sellerId`) and `listingStatus` (`listings\listings.service.ts:294`, `listingStatus`).
- Repository: `listings\listings.repository.ts:692` (`findById`). It uses `findFirst` with `NOT_DELETED`, so a soft-deleted listing reads as gone (`listings\listings.repository.ts:689`, `soft-deleted`).
- Tests: `listings\listings.service.spec.ts:911` (`describe('findById'`), `listings\listings.repository.spec.ts:940` (`findById reads a deleted listing as gone`).

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\listingsApi.ts:307` (`getListing`)

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- `lib\api.ts:158` (`AdminListingDetail`)
- `lib\sellerApi.ts:438` (`ListingDetail`)

## Declared contract
- Path param `id`: a plain `@Param('id') id: string` (`listings\listings.controller.ts:376`, `@Param`). There is no DTO, no pipe and no format validation.
- Query, body and headers: none are declared. The optional `Authorization: Bearer` header is read implicitly by the passport guard.
- Success response: the `toListingDto` object. It is cached under the key `listing:${id}` (`listings\listings.service.ts:770`, `cacheKey`) and shared by all callers.
- Errors in code: 404 `Listing not found` when the row is missing or soft-deleted (`listings\listings.service.ts:775`, `NotFoundException`). Also 404 for a `pending_approval` listing when the viewer is neither owner nor admin (`listings\listings.service.ts:787`, `NotFoundException`). No 401 or 403 is possible on this route.
- OpenAPI: not verified (see scope note).

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|------|------|----------|----------|-------|-----------|
| 1 | No request params beyond path `id`, so there are no unused request items | query/body | none | `listings\listings.controller.ts:376` (`findById`) | backend | high |
| 2 | `sellerId` is returned in the DTO and used for the owner check | response | not unused (A4) | `listings\listings.service.ts:784` (`isOwner`) | backend | high |
| 3 | Response-field usage in the app (A3) was not enumerated field by field. The mobile `ListingDto` type and the web `ListingDetail` type were not diffed against the response. | response | A3 not assessed | `apps\mobile\src\services\listingsApi.ts:308` (`ListingDto`) | mobile and web | low |
| 4 | The mobile `token` argument is optional, and only seller screens pass it. The guest and buyer paths (`productsStore`, `ResumeDraft`) never send it. For those callers the owner or admin branch is dead, which is expected. | request header | A1 (partial) | `apps\mobile\src\store\productsStore.ts:224` (`getListing`), `apps\mobile\src\screens\profile\ResumeDraft.tsx:39` (`getListing`) | mobile buyer and guest | high |

## Looks unused but keep
- The optional `token` argument of `getListing` is needed. Without it, a seller opening their own `pending_approval` listing gets a 404 (`apps\mobile\src\services\listingsApi.ts:303`, `pending_approval`).
- The cache read is kept, and the visibility check is re-run on every request, including on a cache hit (`listings\listings.service.ts:786`, `HIDDEN_FROM_PUBLIC_STATUS`).

## Could not verify
- The OpenAPI operation for `/listings/{id}`: params, documented statuses and response schema. The file is minified and the search tool omits long lines.
- Full A3 analysis of response fields. I did not diff the DTO against the mobile and web readers.
- Cache TTL and cache invalidation on a status change.
- Whether the web admin detail page and the seller edit page call these web helpers. The helpers are declared at `lib\api.ts:158` and `lib\sellerApi.ts:438`, but I did not trace their page callers.
- The sheet's "Flow 3, 18, 26". The flow definitions were not found.

## Sheet check
**Mismatch on the Title, and partly on the Usage Note. Method and path match.**
- Title: "a draft or removed listing is not visible to any user other than its owner or an Admin."
  - The code gates only `pending_approval` (`listings\listings.service.ts:60`, `HIDDEN_FROM_PUBLIC_STATUS`). The comment says `draft`, `rejected` and `inactive` stay reachable by design (`listings\listings.service.ts:48-54`, `draft`).
  - The service test asserts that `draft`, `rejected` and `inactive` are still returned to a buyer (`listings\listings.service.spec.ts:965`, `it.each(['draft', 'rejected', 'inactive']`).
  - A soft-deleted ("removed") listing 404s for everyone, including the owner and admins (`listings\listings.repository.ts:693`, `findFirst`). This differs from "not visible to any user other than owner or Admin".
  - So the sheet requirement conflicts with the documented and tested behaviour. See the matrix.
- Method and path: `GET /listings/:id` matches the code (`listings\listings.controller.ts:374`, `@Get(':id')`). I did not verify the global prefix.
- "Used in App? YES" is correct. Mobile call sites, all through `getListing` at `apps\mobile\src\services\listingsApi.ts:308`:
  - Guest and buyer: `apps\mobile\src\store\productsStore.ts:224` (`getListing`), without a token. `apps\mobile\src\screens\profile\ResumeDraft.tsx:39` (`getListing`), without a token.
  - Seller, with a token: `apps\mobile\src\screens\profile\SellerEditPrice.tsx:61` (`getListing`), `apps\mobile\src\screens\profile\SellerListingDetail.tsx:89` (`getListing`), `apps\mobile\src\screens\profile\SellerListingStatus.tsx:36` (`getListing`).
- Web helpers (the sheet row names no web use): `apps\web\src\lib\api.ts:158` (`AdminListingDetail`, admin) and `apps\web\src\lib\sellerApi.ts:438` (`ListingDetail`, seller).
- The Usage Note's flow numbers could not be matched to anything.

## Test design inputs
### Roles and permissions
- Anyone may call the route. It uses `OptionalJwtAuthGuard`, so a bad token is treated as anonymous and never returns 401 (`auth\guards\optional-jwt-auth.guard.ts:15`, `user || undefined`).

### Ownership
- The owner is decided by `viewer.id === result.sellerId` (`listings\listings.service.ts:784`, `isOwner`).
- The admin is decided by `Role.ADMIN` (`listings\listings.service.ts:785`, `isAdmin`).
- The owner and admin bypass applies only to `pending_approval`.

### Resource states
Enum values: `draft`, `active`, `pending_approval`, `approved`, `rejected`, `inactive`, `sold`, `reserved` (`prisma\schema.prisma:36`, `enum ListingStatus`; this path is relative to `apps\api\`).

Visibility by state, per code:
- `approved`, `active`, `sold`, `reserved`, `draft`, `rejected`, `inactive`: 200 for everyone (the last three per the `listings\listings.service.spec.ts:965` test).
- `pending_approval`: 200 for the owner and an admin, 404 for everyone else.
- Soft-deleted (`deletedAt` set): 404 for everyone. The `deletedAt` field is at `prisma\schema.prisma:801`.

### Validation and error paths
- 404 from an unknown or non-existent id.
- Any string is accepted as an id, with no 400 path. A non-cuid string simply 404s (assumed; not run).
- 5xx paths are not analysed.
- The 404 body shape is the Nest default, `{statusCode, message: 'Listing not found', error}`. This is inferred from `NotFoundException`.

### Response contract
- `toListingDto` at `listings\listings.service.ts:240`. It has no `offerCount` (`listings\listings.service.spec.ts:945`, `does not expose an offer count`). It has `listingStatus` and `sellerId`.
- The response is not role-dependent. The same DTO goes to every viewer who passes the gate.
- OpenAPI schema presence: not verified.

### Business logic
- Read-only, but it uses a shared cache (`listings\listings.service.ts:771`, `cacheManager`). The gate re-runs per request (`listings\listings.service.spec.ts:999`, `re-applies the visibility gate on a cache hit`).
- Cache staleness on a status change was not checked. A status change might let a stale DTO be served until the cache entry expires (assumed risk; not verified).

### Existing tests and docs
- `listings\listings.service.spec.ts:956` (`hides a pending_approval listing`): 404 for anonymous.
- `listings\listings.service.spec.ts:965` (`it.each(['draft', 'rejected', 'inactive']`): 200 for a buyer.
- `listings\listings.service.spec.ts:974` (`still lets the listing's own seller see it`) and `listings\listings.service.spec.ts:980` (`still lets an admin see`): owner and admin allowed.
- `listings\listings.service.spec.ts:986` (`it.each(['sold', 'reserved']`): 200.
- `listings\listings.repository.spec.ts:940`: a soft-deleted listing reads as gone.
- Docs: `docs\fix\README.md:66` (`BRI-800`) records that `GET /listings/:id` 404s `pending_approval` for non-owner and non-admin callers.
- Code comment `listings\listings.service.ts:48` (`GET /listings/:id`) cites BRI-636 and BRI-46's LI26.

### Fixtures needed
- One listing in each state.
- One soft-deleted listing.
- A seller owner account, a non-owner buyer account, an admin account, and an unauthenticated session.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| A draft listing is hidden from non-owner and non-admin callers | Sheet: hidden | not verified | Not hidden: `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`) | `listings\listings.service.spec.ts:965` (`it.each(['draft', 'rejected', 'inactive']`) asserts 200 | Conflict: do not trust the expected result for `draft` until clarified |
| A "removed" (soft-deleted) listing is hidden from non-owner and non-admin callers | Sheet: visible to owner or admin only | not verified | 404 for everyone, including the owner: `listings\listings.repository.ts:693` (`findFirst`) | `listings\listings.repository.spec.ts:940` | Conflict: the sheet's owner/admin exception does not hold |
| A `pending_approval` listing is hidden from the public, but visible to the owner and an admin | Not in sheet; BRI-636 in `docs\fix\README.md:66` | not verified | `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`) | `listings\listings.service.spec.ts:956` | Agree (code, tests and docs agree). The sheet does not state it. |
| `rejected` and `inactive` are visible to buyers | Sheet silent ("removed" is ambiguous) | not verified | `listings\listings.service.ts:48` (`draft`) comment says intentional | `listings\listings.service.spec.ts:965` | Unspecified-in-requirement |
| Unknown id returns 404 | Not stated | not verified | `listings\listings.service.ts:775` (`NotFoundException`) | `listings\listings.service.spec.ts:921` | Agree on code and tests; the OpenAPI side was not checked |
| An invalid token is treated as anonymous (no 401) | Not stated | not verified | `auth\guards\optional-jwt-auth.guard.ts:14` (`handleRequest`) | `auth\guards\optional-jwt-auth.guard.spec.ts:3` (`OptionalJwtAuthGuard`) | Unspecified-in-requirement; the guard spec was not opened, so its assertions are unchecked |

## Suggested test scenarios
| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Anonymous GETs a `pending_approval` listing | anon | n/a | `pending_approval` | 404 | message `Listing not found` | Existing test, Backend code | Assumed: BRI-636 is not in the sheet row | Status-only | Fixture id. Schemathesis can send it. |
| 2 | Non-owner buyer GETs a `pending_approval` listing | buyer | non-owner | `pending_approval` | 404 | Same message as #1 | Existing test | Assumed | Business-rule | Buyer token and fixture. Another method needed. |
| 3 | Owner seller GETs their own `pending_approval` listing | seller | owner | `pending_approval` | 200 | `listingStatus` is `pending_approval`; `sellerId` equals the caller | Existing test | Assumed | Business-rule | Owner token. Another method needed. |
| 4 | Admin GETs a `pending_approval` listing | admin | n/a | `pending_approval` | 200 | `listingStatus` is `pending_approval` | Existing test | Assumed | Business-rule | Admin token. Another method needed. |
| 5 | Anonymous GETs a `draft` listing | anon | n/a | `draft` | Sheet implies 404; code returns 200 | n/a | Sheet vs Backend code | Conflict | Business-rule | Run only after clarification. Expected result untrustworthy. |
| 6 | Anonymous GETs `rejected` and `inactive` listings | anon | n/a | each state | 200 per code | `listingStatus` equals the state | Backend code, Existing test | Unclear | Response-content | Fixtures. Another method needed. |
| 7 | Anonymous GETs a soft-deleted listing | anon | n/a | `deletedAt` set | 404 | message `Listing not found` | Backend code | Assumed | Status-only | A soft-deleted fixture. |
| 8 | Owner GETs their own soft-deleted listing | seller | owner | `deletedAt` set | Sheet implies 200; code returns 404 | n/a | Sheet vs Backend code | Conflict | Business-rule | Run only after clarification. |
| 9 | Cache bypass: a buyer fetches a live listing (200), the seller then moves it to `pending_approval` and the buyer fetches it again | buyer | non-owner | status change between calls | 404 on the second fetch | n/a | Existing test, Backend code | Assumed | Business-rule | A seller token and an update call. Another method needed. |
| 10 | Unknown id, and a malformed id (odd characters) | anon | n/a | `id` is `nonexistent-id`, `%00`, or a very long string | 404; never 5xx | Nest error body | QA suggestion | Assumed | Status-only | Schemathesis can run it. |
| 11 | Invalid, expired or garbage Bearer token on a public listing | anon | n/a | live listing | 200 (treated as anonymous) | DTO is returned | Backend code | Assumed | Status-only | Schemathesis can send it. |
| 12 | A live listing returns no `offerCount` | anon | n/a | live listing | 200 | no `offerCount` field | Existing test | Assumed | Response-content | A live fixture. |
| 13 | Unexpected query params and a body on GET | anon | n/a | `?status=draft` | 200, params ignored | n/a | QA suggestion | Assumed | Security | Schemathesis can send it. |

## Summary: 0 unused request items, 0 unused response fields (A3 not assessed), 0 dead files/branches, 2 conflicts (draft visibility, soft-deleted listing visibility), 13 suggested scenarios
