# Endpoint #32 - GET /brands

Note: I did not read the existing audits, golden, testcases or reports folders. Only `apps\mobile` was searched for the mobile client. For `apps\web` I only grepped for `/brands`, so web A3 is not assessed in depth.

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- `brands\brands.controller.ts:6` (`@Controller('brands')`) and `brands\brands.controller.ts:12` (`findAll`). There is no guard, no role decorator, no params and no DTO.
- `brands\brands.service.ts:8` (`findAll`) is a pass-through.
- `brands\brands.repository.ts:12` (`findAll`) queries Prisma with `orderBy: { name: 'asc' }`, includes a live-listing `_count`, and maps it to `itemCount` at line 22.
- `brands\brands.repository.ts:6` (`BrandWithItemCount`) is the return type.
- `listings\listing.constants.ts:89` (`LIVE_LISTING_WHERE`) defines "live": status approved or active, not soft-deleted, and the seller not mid-deletion.
- The Prisma model is at `D:\Redspur_Backend\redspur-droplight\apps\api\prisma\schema.prisma:514` (`model Brand`). It has id, name, slug, logo, navigationTab and createdAt.

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\brandsApi.ts:13` (`getBrands`) calls GET `/brands` at line 14.
- `services\brandsApi.ts:23` (`getBrandById`) calls `getBrands` at line 24 and filters client-side.
- `types\domain.ts:26` (`Brand`) has id, name and itemCount.

## Declared contract
- **Request:** no path, query, header or body inputs. OpenAPI `schemathesis\spec\openapi.pretty.json:1180-1194` has `"parameters": []`.
- **Response in code:** an array of Brand rows with the extra field `itemCount`. Fields are id, name, slug, logo (nullable), navigationTab, createdAt and itemCount. The repository returns the full Prisma row via a spread (`brands\brands.repository.ts:22`), so fields are whatever the model has. Confidence is medium for that reason.
- **OpenAPI:** only a 200 with an empty description (`schemathesis\spec\openapi.pretty.json:1186-1188`). There is no response schema, no 429 and no 5xx.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | `slug` is returned but dropped by the mobile mapper | response | A3 | `services\brandsApi.ts:15` (`itemCount`) maps only id, name and itemCount. `services\brandsApi.ts:7` (`slug`) is declared in `RawBrand` and never mapped. | Unused in mobile. Web admin uses a different route (`D:\Redspur_Backend\redspur-droplight\apps\web\src\lib\api.ts:373`, `/admin/taxonomy/brands`) and has no call to public `/brands`. | high |
| 2 | `logo` is returned but dropped by the mobile mapper | response | A3 | `services\brandsApi.ts:8` (`logo`) is declared in `RawBrand` and not mapped at line 15. The BrandListing comment says brands show no image (`screens\guest\BrandListing.tsx:22-24`). | Unused in mobile | high |
| 3 | `navigationTab` and `createdAt` are returned but not declared in the mobile `RawBrand` or `Brand` types | response | A3 | `services\brandsApi.ts:4-10` has no `navigationTab` or `createdAt`; `D:\Redspur_Backend\redspur-droplight\apps\api\prisma\schema.prisma:519` (`navigationTab`) | Unused in mobile | high |
| 4 | `itemCount` is read by the SearchLanding screen | response | A4 | `screens\search\SearchLanding.tsx:243` (`b.itemCount`) | Read by SearchLanding only. No other screen read was found in the grep. | med |
| 5 | The mobile comments say the endpoint returns "admin's insertion order", but the code sorts by name | branch | Conflict | `screens\guest\BrandListing.tsx:26-27` (`GET /brands`); `brands\brands.repository.ts:14` (`orderBy`) | Explore's "first 6" taster depends on this order. See the matrix. | high |
| 6 | `getBrandById` fetches the entire list to find one brand | file | Inefficiency, not a defect category | `services\brandsApi.ts:24` (`getBrands`); the comment at `services\brandsApi.ts:19-20` says no `GET /brands/:id` route exists | `screens\home\BrandPage.tsx:114` | high |
| 7 | `BrandsService.findById` and `findNavigationTabBrands` are not on this endpoint's path | file | B5 (belongs to other consumers) | `brands\brands.service.ts:12` (`findById`), `brands\brands.service.ts:16` (`findNavigationTabBrands`) | Used by other modules (listings, saved-searches, embeddings import `BrandsService`). | med |

There are no B1-B3 items, because the endpoint takes no inputs.

## Looks unused but keep (and why)
- `slug`, `logo`, `navigationTab` and `createdAt` are on the response but not mapped by the mobile client. They may serve other or future clients and the spec does not say they are removable. `logo` and `slug` are part of the BRI-114 brand taxonomy according to the comment at `screens\guest\BrandListing.tsx:23`.
- `getBrandById` exists only because there is no `GET /brands/:id`.

## Could not verify
- Whether the web app calls the public `/brands`. A grep of `apps` found only `/admin/taxonomy/brands` in web.
- I did not open every mobile call site to check which fields it reads. A3 for mobile is based on the mapper at `services\brandsApi.ts:15`, which drops everything except id, name and itemCount.
- The KB "BRI-407" and "BRI-114" tickets were not checked in Linear. They appear only in code comments.
- No e2e test for public `GET /brands` exists. The only brand e2e tests are the admin ones at `D:\Redspur_Backend\redspur-droplight\apps\api\test\admin.e2e-spec.ts:176`.

## Knowledge base cross-check
- `qa-knowledge\gaps-and-conflicts.md:54` and `business-rules.json` BR-BRANDS-001 (alphabetical by name) are confirmed by `brands\brands.repository.ts:14` (`orderBy`).
- BR-BRANDS-002 (`itemCount` counts live listings, computed fresh) is confirmed by `brands\brands.repository.ts:17` (`LIVE_LISTING_WHERE`). Both rules are code-only and stay "Assumed".
- Conflict between KB/code and the mobile comments: the mobile comments claim insertion order (`screens\guest\BrandListing.tsx:26`), but the code sorts by name. The KB does not mention this mobile claim.
- The KB's "explained asymmetry" note is a gap with no requirement behind it.

## Sheet check
- **Method and path:** Match. The route is `brands` + `@Get()` (`brands\brands.controller.ts:6`).
- **Module:** Mismatch. The sheet says "Categories", but the code lives in the `brands` module (`brands\brands.module.ts`) and the spec tag is "Brands" (`schemathesis\spec\openapi.pretty.json:1190-1192`).
- **Title:** "Brands Controller find All" matches `BrandsController_findAll` (`schemathesis\spec\openapi.pretty.json:1182`).
- **Used in App:** YES is correct. Mobile call sites are:
  - `hooks\useFilterLabels.ts:90`
  - `screens\sell\SellFieldSheet.tsx:144`
  - `screens\sell\SellAIReview.tsx:248`
  - `screens\home\BrandPage.tsx:114` (via `getBrandById`)
  - `screens\auth\setup\Brands.tsx:42`
  - `screens\guest\BrandListing.tsx:40`
  - `screens\search\SearchLanding.tsx:74`
  - `screens\modals\Filters.tsx:201`
  - `screens\guest\Explore.tsx:101`
  - `screens\profile\PrefBrands.tsx:47`
- **Admin web:** no call to public `/brands`. It uses `/admin/taxonomy/brands`.
- **Flow 2, 6 in the Usage Note:** I cannot map these flow numbers to the call sites.

## Test design inputs
- **Roles:** anonymous access is allowed. `brands\brands.controller.ts:6` has no guard, so every role gets the same result. Whether a global guard applies is not verified.
- **Ownership:** none.
- **Resource states:** brands have no status. `itemCount` counts only listings that are approved or active, not soft-deleted, with a seller not mid-deletion (`listings\listing.constants.ts:89`). Draft, pending, rejected, sold or reserved listings are excluded.
- **Validation and errors:** there are no inputs. The only error path is a database failure returning 500. The 429 throttle is not verified.
- **Response contract:** a bare array, not paginated, with no spec schema. An empty table returns `[]`.
- **Business logic:** read-only. There are no side effects, and `itemCount` is not cached.
- **Existing tests:** `brands\brands.repository.spec.ts:13` covers only `findNavigationTabBrands`. I found no spec that asserts `findAll` ordering or `itemCount`.
- **Mobile tests:** `screens\guest\__tests__\BrandListing.test.tsx:40` mocks the order assumption.
- **Fixtures:** brands with live listings, brands with only non-live listings, a brand with a soft-deleted listing, a brand whose seller is mid-deletion, and a brand with no listings.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| Public list of all brands | Title "find All" | 200 only, no schema (`schemathesis\spec\openapi.pretty.json:1186`) | `brands\brands.controller.ts:12` (`findAll`) | none | Spec-gap |
| Ordering | Mobile comment says admin insertion order (BRI-407, comment only) | not specified | `brands\brands.repository.ts:14` (`orderBy`) sorts by name asc | none | Conflict. Order-dependent cases (Explore "first 6") have no trustworthy expected result. |
| `itemCount` semantics | none | not specified | `brands\brands.repository.ts:17` (`LIVE_LISTING_WHERE`) | none | Unspecified-in-requirement |
| Auth | none | no security declared in the snippet | no guard on the controller | none | Unspecified-in-requirement |

## Suggested test scenarios
All scenarios are Assumed (QA suggestion) unless noted.
| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Req status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | List brands anonymously | anon | n/a | none | 200 | JSON array | Backend code | Assumed | Status-only | Schemathesis can run it |
| 2 | Same call as a buyer, seller and admin | each | n/a | none | 200 | identical body | QA suggestion | Assumed | Status-only | needs accounts |
| 3 | Item shape | anon | n/a | seeded brands | 200 | each item has string id, name, slug, nullable logo, integer itemCount >= 0 | Backend code | Assumed | Contract | spec has no schema, so a manual schema check is needed |
| 4 | Ordering | anon | n/a | brands "B", "a", "C" | 200 | order by name asc. Hold until the order conflict is resolved. | Conflict | Conflict | Business-rule | seeded fixtures |
| 5 | `itemCount` counts only live listings | anon | n/a | brand with approved, active, draft, rejected, deleted and leaving-seller listings | 200 | itemCount equals live count only | Backend code | Assumed | Business-rule | seeded data |
| 6 | `itemCount` is 0 for a brand with no listings | anon | n/a | empty brand | 200 | itemCount 0 | QA suggestion | Assumed | Business-rule | fixture |
| 7 | Empty table | anon | n/a | no brands | 200 | `[]` | QA suggestion | Assumed | Response-content | clean DB |
| 8 | Unexpected query params (`?limit=1&q='; DROP`) | anon | n/a | junk query | 200 | unchanged full list, no 500 | QA suggestion | Assumed | Security | Schemathesis can run it |
| 9 | Unsupported methods (POST/PUT/DELETE `/brands`) | anon | n/a | none | 404 or 405, not 5xx | not 5xx | QA suggestion | Assumed | Security | Schemathesis can run it |
| 10 | Auth header junk (invalid bearer) | anon | n/a | bad token | 200 if truly public | same as anonymous | QA suggestion | Assumed | Security | Unclear whether the route is public. Verify the global guard. |
| 11 | Repeated calls after a listing is approved or deleted | anon | n/a | before/after | 200 | itemCount changes immediately because it is uncached | Backend code | Assumed | Business-rule | seeded data |

## Summary: 0 unused request items, 4 unused response fields (slug, logo, navigationTab, createdAt in mobile), 1 dead-or-n/a file/branch (B5 for `findById`/`findNavigationTabBrands`, which other modules use), 1 conflict (ordering), 11 suggested scenarios
