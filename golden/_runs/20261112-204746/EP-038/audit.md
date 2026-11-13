# Endpoint #38 (EP-038) - GET /listings/:id

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route and guard: `listings\listings.controller.ts:374` (`@Get(':id')`), guard `listings\listings.controller.ts:375` (`OptionalJwtAuthGuard`), handler `listings\listings.controller.ts:376` (`findById`). No `@Roles`, no DTO or pipe on `id` (plain string).
- Service: `listings\listings.service.ts:769` (`findById`). The visibility gate is at `listings\listings.service.ts:786` (`HIDDEN_FROM_PUBLIC_STATUS`). The constant is defined at `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`).
- Repository: `listings\listings.repository.ts:692` (`findById`). It uses `findFirst` with `NOT_DELETED` (soft-deleted rows are hidden), plus seller, brand, category, images, attribute values and counts includes.
- Cache: `listings\listings.service.ts:770` (`cacheKey`). The key is `listing:<id>` and is shared across all callers. It is invalidated at `listings\listings.service.ts:2161` (`cacheManager`) on delete, and at other writes (lines 1230, 1385, 1403, 1431, 1609).
- Mapper: `toListingDto` (called at `listings\listings.service.ts:776`). I did not open its file, so the exact field list is not verified. The service reads `result.sellerId` and `result.listingStatus` from it, so those two exist.
- Existing unit tests: `listings\listings.service.spec.ts:911-993` (`describe('findById'`). Also `listings\listings.repository.spec.ts:940` (soft-deleted read).

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- API client: `services\listingsApi.ts:307` (`getListing`). The token is optional.
- Call sites:
  - `store\productsStore.ts:224` (`fetchListing`), which feeds the product detail screen.
  - `screens\profile\ResumeDraft.tsx:39`
  - `screens\profile\SellerListingDetail.tsx:89`
  - `screens\profile\SellerEditPrice.tsx:61`
  - `screens\profile\SellerListingStatus.tsx:36`
  - `screens\modals\MakeOffer` (tests only at `screens\modals\__tests__\MakeOffer.test.tsx:252`). I did not find the non-test call site, so I treat it as indirect via the store.

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- `lib\api.ts:157` (`getListing`, admin client), used at `app\admin\listings\[id]\page.tsx:61`.
- `lib\sellerApi.ts:437` (`getListing`), used at `app\seller\listings\[id]\edit\page.tsx:84`.

## Declared contract
- Request: path param `id` (string, no format check), optional `Authorization` bearer. No query params, no body.
- OpenAPI (`schemathesis\spec\openapi.pretty.json:1551-1572`): `get`, operationId `ListingsController_findById`, path param `id` string required, only a `200` response with an empty description and no schema.
  - Not documented: 404, and the 401 case for a bad token (`OptionalJwtAuthGuard` behaviour with an invalid token was not verified).
  - Not declared: any bearer security requirement.
- Code behaviour:
  - 200 returns the listing DTO.
  - 404 `Listing not found` for an unknown id, a soft-deleted listing (`listings\listings.repository.ts:694`), or a `pending_approval` listing viewed by anyone other than the owner or an admin (`listings\listings.service.ts:786`).
- Response fields: the DTO comes from `toListingDto`, which was not opened. Field-level A3 is not possible from the DTO source (see Could not verify).

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | Sheet requirement says "draft or removed" is hidden from non-owners. Code gates only `pending_approval`. `draft`, `rejected` and `inactive` stay publicly readable by design (BRI-44). | branch | Requirement/code mismatch (not B/A) | `listings\listings.service.ts:60` (`HIDDEN_FROM_PUBLIC_STATUS`), `listings\listings.service.ts:48-59` (comment), `listings\listings.service.spec.ts:965` (`it.each(['draft', 'rejected', 'inactive']`) | all clients | high |
| 2 | "Removed" (soft-deleted) listings 404 for EVERYONE, including the owner and admins, via `findFirst` with `NOT_DELETED`. The title says only "other than owner/Admin". | branch | Requirement/code mismatch | `listings\listings.repository.ts:694` (`NOT_DELETED`) | all | high |
| 3 | The owner/admin branch is exercised only for `pending_approval`. It is never needed for `draft` because draft is open to all. | branch | B3-like (owner/admin bypass is only meaningful for one status) | `listings\listings.service.ts:784-786` (`isOwner`) | backend | med |
| 4 | Every web and mobile caller sends the token except the web admin and seller helpers, and the mobile product detail path. For web, `request()` adds auth in the helper; I did not verify this. | header | A1 (low) | `apps\web\src\lib\api.ts:157` (`getListing`) | web | low |
| 5 | The `404` and the error body are not documented in OpenAPI, and there is no response schema. | response | Spec-gap | `schemathesis\spec\openapi.pretty.json:1564-1567` | spec | high |
| 6 | Cache stores the full DTO under `listing:<id>`, with the gate applied afterwards per request. This is safe for visibility. A stale window exists only if a write path forgets to invalidate. | file | Risk lead | `listings\listings.service.ts:771` (`cacheKey`) | backend | med |

B1, B2, B4 and B5: nothing found for the inputs. `id` is used in the query and the cache key.

## Looks unused but keep (and why)
- `req.user` / `viewer`: optional, but required for the owner and admin bypass (BRI-636) and for owner reads of their own `pending_approval` listing (mobile comment at `services\listingsApi.ts:302-306`).
- The `token` argument of mobile `getListing`: needed for the owner of a paused or pending listing.

## Could not verify (and what I checked)
- Response DTO field list and the A3 per-field diff against mobile `ListingDto`, web `ListingDetail` and `AdminListingDetail`. I did not open `toListingDto` or the TS types, so A3 is **not assessed**. The blocker was time, not a technical barrier. It is incomplete and should be done as a follow-up.
- Invalid or expired token behaviour in `OptionalJwtAuthGuard` (401 versus anonymous fallthrough). I did not open the guard.
- The Flow 3, 18 and 26 definitions. I had no access to the flow documents. The mobile call sites above are consistent with a detail view (3), seller screens (18) and deep links or chat (26) but this is not confirmed.
- The admin web detail page calling `GET /listings/:id` for a `pending_approval` or soft-deleted listing: the first works because the admin bypass exists, the second would 404 (`listings\listings.repository.ts:694`). I did not verify whether the admin page has another path for deleted listings.

## Knowledge base cross-check
- Consulted `qa-knowledge\modules\listings.md:122-127` (section for this endpoint) and `qa-knowledge\endpoint-inventory.json:2943`. I did not open `business-rules.json` in detail beyond grep hits. No gaps entry was found for this endpoint.
- Confirmed (re-verified in code this run): the `OptionalJwtAuthGuard`, the cache key `listing:<id>` shared across callers with the per-request gate applied after, only `pending_approval` being hidden, and `draft`/`rejected`/`inactive` staying reachable (`listings\listings.service.ts:48-60`). The KB also lists `sold` and `reserved` as reachable, which matches the spec at `listings\listings.service.spec.ts:986`.
- Disagreement: none with the code. The KB itself documents the mismatch with the sheet title (draft is not hidden).
- KB lacks: the soft-deleted 404 for owners and admins, and a test scenario list for this endpoint.

## Sheet check
- Method and path: Matches. `@Get(':id')` at `listings\listings.controller.ts:374` under the listings controller. I did not verify the global prefix.
- Used in App? YES: Matches. Mobile call sites are listed above. Web has two call sites, admin and seller edit.
- Usage Note "Flow 3, 18, 26": Not verified (flow definitions unavailable). Indirect plausibility only. The web admin and seller edit usages are not mentioned in the note.
- Title: Mismatch with code. The title claims draft and removed are hidden from everyone but the owner or an admin. Code hides only `pending_approval` for non-owners, and removed (soft-deleted) listings are hidden from everyone. The BRI-636 tests at `listings\listings.service.spec.ts:965` explicitly assert that draft is returned to a buyer.

## Test design inputs
- **Roles and permissions**: anyone may call (anon, buyer, seller, admin). There is no 401 for a missing token (`listings\listings.controller.ts:375`). Owner and admin get through for `pending_approval` (`listings\listings.service.ts:784-786`).
- **Ownership**: decided by `viewer.id === result.sellerId`. Cross-account access to draft, rejected, inactive, sold and reserved is allowed (open to all). Pending_approval is hidden from non-owners.
- **Resource states** (enum `apps\api\prisma\schema.prisma:36-44`): draft, active, pending_approval, approved, rejected, inactive, sold, reserved, plus soft-deleted.
  - Pending_approval: 404 for anon and non-owners; 200 for the owner and admins.
  - Soft-deleted: 404 for all.
  - Every other status: 200 for all.
- **Validation and error paths**: only 404 (`Listing not found`, NestJS standard error body, assumed). The `id` is unvalidated, so odd strings give 404. A 500 is not expected. I did not check what a very long or non-cuid id does.
- **Response contract**: DTO from `toListingDto`, including `sellerId` and `listingStatus`. There is no role-dependent shape (the DTO is shared and cached). The OpenAPI response has no schema.
- **Business logic**: read only. A per-id cache is filled on first read and shared. I did not see a view counter increment here (not verified).
- **Existing tests**: `listings\listings.service.spec.ts:956` (pending hidden from anon), `:965` (draft/rejected/inactive returned), `:974` (owner sees pending), `:980` (admin sees pending), `:986` (sold/reserved shown); repo `listings\listings.repository.spec.ts:940` (soft-deleted read as gone). Mobile tests include `screens\home\__tests__\ProductDetail.test.tsx:503` (404 handling) and `screens\profile\__tests__\SellerListingStatus.test.tsx:63` (token passed).
- **Fixtures** (`D:\API_workflow\schemathesis\fixtures.json:3-11`): one id per state (draft, pending_approval, approved, active, rejected, inactive, sold, reserved), all owned by the ST_USER account. Needed but missing: a soft-deleted listing (the readme at line 2 says none exists), a second non-owner account, an admin account, and a listing owned by another seller.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| Draft listing hidden from non-owner | Sheet title: hidden from non-owner/non-admin | No schema or 404 documented | Not hidden: `listings\listings.service.ts:60` | `listings\listings.service.spec.ts:965` asserts it is returned | Conflict (need product owner to say whether the title or BRI-44/BRI-636 governs) |
| Soft-deleted ("removed") hidden | Sheet title says only owner/admin can see | 404 undocumented | 404 for everyone: `listings\listings.repository.ts:694` | `listings\listings.repository.spec.ts:940` | Conflict (owner and admin also get 404) |
| Pending_approval hidden except owner/admin | Not in the sheet title; BRI-636 | Undocumented | `listings\listings.service.ts:786` | `listings\listings.service.spec.ts:956-984` | Unspecified-in-sheet (ticket-backed) |
| Rejected/inactive visible to all | Not stated | Undocumented | Returned: `listings\listings.service.ts:48-59` | `listings\listings.service.spec.ts:965` | Unspecified-in-requirement |
| Anonymous access | Not stated | No security declared | `listings\listings.controller.ts:375` | n/a | Agree (spec has none) |
| Error response 404 | Not stated | Absent | `listings\listings.service.ts:775` | `listings\listings.service.spec.ts:920` | Spec-gap |

## Suggested test scenarios
| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Anon reads draft listing | anon | non-owner | draft fixture | Title says 404; code gives 200 | Record both | Requirement (title) vs code | Conflict | Business-rule | Draft id; cannot be judged until clarified |
| 2 | Non-owner buyer reads draft | buyer | non-owner | draft | same as 1 | same | Requirement vs code | Conflict | Security | Second account |
| 3 | Owner reads draft | seller | owner | draft | 200 | `listingStatus` = draft | Requirement | Confirmed | Response-content | owner token |
| 4 | Admin reads draft | admin | n/a | draft | 200 | `listingStatus` = draft | Requirement | Confirmed | Response-content | admin token |
| 5 | Anon reads pending_approval | anon | non-owner | pending id | 404 | error body "Listing not found" | BRI-636 (code comment) | Confirmed (ticket named in code) | Security | pending id |
| 6 | Buyer reads pending_approval | buyer | non-owner | pending | 404 | same | BRI-636 | Confirmed | Security | second account |
| 7 | Owner reads pending_approval | seller | owner | pending | 200 | `listingStatus` = pending_approval | BRI-636 | Confirmed | Business-rule | owner token |
| 8 | Admin reads pending_approval | admin | n/a | pending | 200 | same | BRI-636 | Confirmed | Business-rule | admin token |
| 9 | Anon reads soft-deleted listing | anon | n/a | deleted id | 404 | not found | Requirement ("removed") | Confirmed | Security | soft-deleted fixture (missing) |
| 10 | Owner and admin read soft-deleted listing | seller, admin | owner | deleted id | Title implies 200; code gives 404 | record both | Requirement vs code | Conflict | Business-rule | deleted fixture |
| 11 | Anon reads rejected, inactive, sold, reserved, approved, active | anon | non-owner | each fixture | 200 | `listingStatus` matches state | Backend code / tests | Assumed | Response-content | fixtures exist (Schemathesis feasible) |
| 12 | Unknown id | anon | n/a | `nonexistent-id` | 404 | error body | Backend code | Assumed | Status-only | none |
| 13 | Invalid or expired bearer on a public listing | anon | n/a | bad token | Unclear (200 or 401) | not known | QA suggestion | Unclear | Security | none |
| 14 | Cache staleness: delete or pause a listing then read it immediately | seller, anon | owner | state change then GET | latest state, 404 after delete | no stale 200 | QA suggestion | Assumed | Business-rule | write access; manual |
| 15 | Odd ids: very long, URL-encoded, SQL or script strings | anon | n/a | odd id | 404, never 500 | no stack trace | QA suggestion | Assumed | Security | none (Schemathesis can run) |
| 16 | Contract: 200 and 404 schemas present in the spec | n/a | n/a | any | n/a | spec has no schema | OpenAPI spec | Spec-gap | Contract | spec update |

## Summary: 0 unused request items, response fields not assessed (A3 incomplete), 0 dead files, 2 requirement/code conflicts (draft hidden, removed visible to owner/admin) plus 1 spec-gap, 16 suggested scenarios
