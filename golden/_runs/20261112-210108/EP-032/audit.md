# Endpoint #32 - GET /brands

Method and path match the sheet. The code has no global prefix (no `setGlobalPrefix` in `app.module.ts`; `main.ts` was not opened, so a prefix set there is unverified).

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- `brands\brands.controller.ts:6` (`@Controller('brands')`), `brands\brands.controller.ts:11` (`@Get()`), `brands\brands.controller.ts:12` (`findAll`). There are no guards, roles, params or DTOs.
- `brands\brands.service.ts:8` (`findAll`) is a pass-through to the repository.
- `brands\brands.repository.ts:12` (`findAll`) runs the Prisma query. It uses `orderBy name asc` at `brands\brands.repository.ts:14`, and a live-listing `_count` at `brands\brands.repository.ts:17` (`LIVE_LISTING_WHERE`). The response is mapped at `brands\brands.repository.ts:22` (`itemCount`).
- `listings\listing.constants.ts:89` (`LIVE_LISTING_WHERE`) holds the "live" filter: approved or active, not soft-deleted, seller not leaving (`listings\listing.constants.ts:84-92`).
- `brands\brands.module.ts` and `app.module.ts:11` (`BrandsModule`) register the module.
- `app.module.ts:104` (`APP_GUARD`) installs only a global `ThrottlerGuard`, so rate limiting (429) applies and there is no auth.
- The model is `D:\Redspur_Backend\redspur-droplight\apps\api\prisma\schema.prisma:514` (`model Brand`).

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\brandsApi.ts:14` (`getBrands`) is the only call to the endpoint.

## Declared contract
- **Request:** there are no path, query, header or body inputs. The OpenAPI operation (`D:\API_workflow\schemathesis\spec\openapi.pretty.json:1180-1194`, `BrandsController_findAll`) has `"parameters": []`.
- **Response:** a JSON array of the Brand columns plus `itemCount`. Fields are `id`, `name`, `slug`, `logo` (nullable), `navigationTab` and `createdAt` (`schema.prisma:515-520`), plus `itemCount`. The service return type is `BrandWithItemCount[]` (`brands\brands.repository.ts:6`).
- **Spec vs code:** the spec documents only `200`, with `"description": ""` and no response schema (`openapi.pretty.json:1186-1188`). It does not document `429`.
- **Errors:** I found no 4xx path in the handler. A DB failure would return 500, and the global throttler can return 429.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | `slug` returned by the API but never mapped by the mobile client | response | A3 | `services\brandsApi.ts:15` (the mapper keeps only `id`, `name`, `itemCount`; `slug` is declared at `services\brandsApi.ts:7`) | unused in mobile. No web call to the public route (see item 5). | high |
| 2 | `logo` is never read by mobile | response | A3 | `services\brandsApi.ts:8` (declared in `RawBrand`), dropped at `services\brandsApi.ts:15` | unused in mobile | high |
| 3 | `navigationTab` and `createdAt` are returned but absent from `RawBrand` and the mapper | response | A3 | `services\brandsApi.ts:4-10` (no `navigationTab` or `createdAt` field) | unused in mobile | high |
| 4 | `findNavigationTabBrands` is not called by any `GET /brands` route; it is a service method with no route here | file/branch | B5 | `brands\brands.service.ts:16` (`findNavigationTabBrands`), `brands\brands.repository.ts:29` (`findNavigationTabBrands`) | Other callers outside this endpoint were not checked; the repository spec covers it (`brands\brands.repository.spec.ts:12`). | low |
| 5 | The web admin does not call the public `GET /brands`. It uses `/admin/taxonomy/brands`. | file | - | `D:\Redspur_Backend\redspur-droplight\apps\web\src\lib\api.ts:373` (`/admin/taxonomy/brands`) | web | high |
| 6 | `getBrandById` fetches the whole list and filters client-side because no `GET /brands/:id` exists | file | - | `services\brandsApi.ts:23` (`getBrandById`), `screens\home\BrandPage.tsx:114` (`brandsApi.getBrandById`) | mobile | high |

There are no B1 or B2 items, because the endpoint takes no inputs. There are no B3 or B4 items. `itemCount` is computed from the live-listing `_count` (`brands\brands.repository.ts:22`).

## Looks unused but keep
- `slug` and `logo` are returned by the API. The mobile client discards them, but the `RawBrand` type still declares them (`services\brandsApi.ts:7-8`).
- `Brand.slug` is `@unique` (`schema.prisma:517`), so it is likely meant for stable identification or deep links. This is an assumption.
- `getBrandById` is the workaround for the missing by-id route (`services\brandsApi.ts:19-22`).

## Could not verify
- Whether `main.ts` sets a global prefix. Only the `app.module.ts` match for `setGlobalPrefix` came back empty.
- The `Brand` type in `types\domain` was not opened. I assume it has `id`, `name` and `itemCount`, based on the mapper at `services\brandsApi.ts:15`.
- Which of the screens named below (`Explore.tsx`, `BrandListing.tsx`, `PrefBrands.tsx`, `BrandPage.tsx`) read `itemCount` or other fields. I did not open them.
- "Flow 2, 6" in the sheet: I have no definition of those flow numbers.
- No sheet row for flows or role-specific usage was checked beyond the call sites below.

## Knowledge base cross-check
- **Consulted:** `endpoint-inventory.json` (the `GET /brands` entry, listed from line 3163), `modules\brands.md`, `business-rules.json` (BR-BRANDS-001 and BR-BRANDS-002), `gaps-and-conflicts.md` (gap 40), and `test-scenarios.md`.
- **Confirmed by re-reading the code:**
  - Alphabetical ordering by name (`brands\brands.repository.ts:14`, `orderBy`).
  - `itemCount` counts live listings (`brands\brands.repository.ts:17`, `LIVE_LISTING_WHERE`), computed on every call with no caching.
  - The KB's "mobile only, no web call to the public route" claim (confirmed at `D:\Redspur_Backend\redspur-droplight\apps\web\src\lib\api.ts:373`, which is the admin route only).
- **Source of those rules:** BR-BRANDS-001 and BR-BRANDS-002 are code-only (`gap-confirmed-by-code` and `confirmed-by-code`). They are Assumed, not requirements.
- **Not found in the KB:** the `slug`, `logo`, `navigationTab` and `createdAt` response-field analysis. The KB cites the controller as lines 9-13, which is slightly off from the current lines 11-14. This is cosmetic and I did not rely on it.

## Sheet check
- **Method and path:** match.
- **Title ("Brands Controller find All"):** matches `BrandsController_findAll`. The OpenAPI summary is "List all brands".
- **Used in App? = YES:** correct. Real call sites, all mobile and all via `brandsApi.getBrands`:
  - `screens\modals\Filters.tsx:201` (`brandsApi.getBrands`)
  - `screens\guest\Explore.tsx:101` (`brandsApi.getBrands`)
  - `screens\guest\BrandListing.tsx:40` (`brandsApi.getBrands`)
  - `screens\sell\SellFieldSheet.tsx:144` (`brandsApi.getBrands`)
  - `screens\sell\SellAIReview.tsx:248` (`brandsApi.getBrands`)
  - `screens\search\SearchLanding.tsx:74` (`getBrands`)
  - `screens\profile\PrefBrands.tsx:46` (`brandsApi`; line 40 is only a comment naming the call)
  - `screens\home\BrandPage.tsx:114` (`brandsApi.getBrandById`, which wraps `getBrands` at `services\brandsApi.ts:24`)
- **Web admin:** no call to the public `GET /brands`.
- **Usage Note "Flow 2, 6":** not verifiable. The call sites span guest, buyer, seller sell flow, search, filters and preferences, so it is broader than two flows.

## Test design inputs
- **Roles:** public, with no guards. Anonymous, buyer, seller and admin all get 200. Only the global throttler can return 429 (`app.module.ts:104`).
- **Ownership:** not applicable.
- **Resource states:** a brand has no status. `itemCount` counts only listings in approved or active status that are not soft-deleted and whose seller is not leaving (`listings\listing.constants.ts:84-92`). A brand with zero listings still appears, with `itemCount` 0. `navigationTab` brands are included, not filtered.
- **Validation and errors:** there are no inputs to validate. Unknown query parameters are not declared. Whether a global ValidationPipe rejects them was not checked.
- **Response contract:** an array of objects with `id`, `name`, `slug`, `logo|null`, `navigationTab`, `createdAt` and `itemCount` (integer). Mobile reads `id`, `name` and `itemCount` only.
- **Business logic:** it is a pure read with no side effects. The count is recomputed per request.
- **Existing tests:**
  - Mobile: `apps\mobile\src\services\__tests__\brandsApi.test.ts:21` asserts the client calls `/brands`.
  - Backend: `brands\brands.repository.spec.ts` only covers `findNavigationTabBrands` (lines 12-16 of the grep output). `brands\brands.service.spec.ts` was not opened.
  - There is no backend e2e for the public `GET /brands`. The e2e `D:\Redspur_Backend\redspur-droplight\apps\api\test\admin.e2e-spec.ts:176` covers the admin route only.
- **Fixtures:** a brand with live listings, a brand with none, a brand whose only listings are soft-deleted, rejected or sold (for count exclusion), and a brand with a `null` logo. `D:\API_workflow\schemathesis\fixtures.json` was not read.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| Public list of all brands, no auth | The sheet title names only the controller method | `GET`, no security declared (`openapi.pretty.json:1180-1194`) | `brands\brands.controller.ts:11` (`@Get()`) | Mobile client test only | Unspecified-in-requirement |
| Response shape | None | No schema (`openapi.pretty.json:1186-1188`) | `brands\brands.repository.ts:6` (`BrandWithItemCount`) | None | Spec-gap |
| Ordering by name ascending | None | None | `brands\brands.repository.ts:14` (`orderBy`) | None | Unspecified-in-requirement |
| `itemCount` counts only live listings | None | None | `brands\brands.repository.ts:17` (`LIVE_LISTING_WHERE`) | None | Unspecified-in-requirement |
| 429 on rate limit | None | Not documented | `app.module.ts:104` (`APP_GUARD`) | None | Spec-gap |

No Conflict rows.

## Suggested test scenarios
All of these are Assumed: no requirement source names expected behaviour for this endpoint.

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Anonymous list brands | anon | n/a | none | 200 | JSON array | Backend code | Assumed | Status-only | Schemathesis (no fixture) |
| 2 | Same call as a buyer, seller and admin | each | n/a | Bearer token | 200 | Same body as anon | QA suggestion | Assumed | Status-only | roles/accounts |
| 3 | Response item shape | anon | n/a | none | 200 | Each item has `id`, `name`, `slug`, `itemCount` (integer, 0 or more), `logo` string or null | Backend code | Assumed | Response-content | Needs a response schema in the spec (currently absent) |
| 4 | Ordering | anon | n/a | 2 or more brands | 200 | `name` ascending | Documentation (qa-knowledge) with `brands\brands.repository.ts:14` | Assumed | Business-rule | Manual or scripted |
| 5 | `itemCount` excludes non-live listings | anon | n/a | Brand with approved, sold, rejected and soft-deleted listings | 200 | Count equals the live ones only | Documentation (qa-knowledge) with `brands\brands.repository.ts:17` | Assumed | Business-rule | Fixtures |
| 6 | Brand with zero live listings is still listed with `itemCount` 0 | anon | n/a | Empty brand | 200 | Brand present, `itemCount` 0 | Backend code | Assumed | Business-rule | Fixture |
| 7 | Unexpected query parameters (`?limit=1`, `?name=x`, injection strings) | anon | n/a | Extra params | 200 expected, ignored | The same full list | QA suggestion | Assumed | Security | Schemathesis negative mode, which fails if a 5xx appears |
| 8 | Wrong method (POST, PUT, DELETE on `/brands`) | anon | n/a | none | 404 or 405 | Not 5xx | QA suggestion | Assumed | Contract | Schemathesis |
| 9 | `GET /brands/{id}` | anon | n/a | Any id | 404 expected (no route) | Not 200 | Backend code, since the mobile comment at `services\brandsApi.ts:19` says no route exists | Assumed | Contract | Schemathesis |
| 10 | Rate limiting under repeated calls | anon | n/a | Burst | 429 after the limit | The throttle limit value was not read | QA suggestion | Assumed | Security | Another method (load script) |
| 11 | Caching/freshness: change a listing's status, then re-fetch | anon | n/a | Before/after | 200 | `itemCount` updates immediately | Documentation (qa-knowledge) | Assumed | Business-rule | Fixture |

## Summary: 0 unused request items, 4 unused response fields in mobile (`slug`, `logo`, `navigationTab`, `createdAt`), 1 possibly dead file or branch (`findNavigationTabBrands`, low confidence), 0 conflicts, 11 suggested scenarios
(Count not verified with a script; the numbers come from reading the code.)
