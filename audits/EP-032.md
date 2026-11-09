# EP-032 Audit — GET /brands

**Module:** Categories
**Method:** GET
**Path:** `/brands`
**Title:** Brands Controller find All
**Used in App?:** YES
**Usage Note (sheet):** Flow 2, 6

---

## Summary

`GET /brands` is a fully public, unauthenticated, parameter-less endpoint that returns every `Brand` row alphabetically (`orderBy: { name: 'asc' }`) along with a computed `itemCount` (count of that brand's live listings). It is genuinely used across at least 8 distinct mobile screens spanning guest, buyer, and seller roles — markedly more than the sheet's "Flow 2, 6" note suggests — but has **no call site in the admin/seller web app** (which uses a separate `/admin/taxonomy/brands` endpoint instead). The headline conflict: app code comments and a feature doc (`brand-drill-down.md`) explicitly assume this endpoint returns brands in "the admin's own insertion/curated order," but the code sorts alphabetically and the `Brand` model has no order/sortOrder column at all to back that assumption — the doc's premise appears unsupported by the data model. Two response fields (`slug`, `logo`) are fetched by the mobile client's raw type but dropped before reaching the UI; two more (`navigationTab`, `createdAt`) are sent by the backend but never even typed by the mobile client.

---

## Files Involved

### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `brands\brands.controller.ts:6-14` (`@Controller('brands')`, `@Get()` `findAll()` — no guards, no params, no DTO)
- Service: `brands\brands.service.ts:8-10` (`findAll()` delegates straight to repository); `:12-18` (`findById`, `findNavigationTabBrands` — not routed, see Finding #7)
- Repository: `brands\brands.repository.ts:12-23` (Prisma query, `orderBy: { name: 'asc' }`, joins live-listing count via `LIVE_LISTING_WHERE`)
- Live-listing filter: `listings\listing.constants.ts:68-92` (`LIVE_LISTING_WHERE` — status `approved`/`active`, not soft-deleted, seller not mid-account-deletion)
- Module: `brands\brands.module.ts:1-11`
- Schema: `prisma\schema.prisma:514-524` (`Brand` model: `id, name, slug, logo?, navigationTab, createdAt` — **no order/sortOrder column**, unlike `Material`)
- Global guard: `app.module.ts:59,104` (`ThrottlerGuard`, 100 req/min/IP — the only gate on this route)
- Tests: `brands\brands.service.spec.ts` (covers `findAll()` delegation + empty array, mocked repo), `brands\brands.repository.spec.ts` (covers ONLY `findNavigationTabBrands()` — see Finding #5)
- Other consumers of the same `BrandsService`/`BrandsRepository` provider, NOT reached via this endpoint (noted to avoid double-counting as dead code): `listings\listings.service.ts:374` (`findById`), `saved-searches\saved-searches.service.ts:78` (`findById`), `embeddings\brand-centroid-cache.service.ts:75`, `embeddings\visual-classification.service.ts:295` (`findNavigationTabBrands`)
- Separate admin-only brand CRUD surface (different endpoint, same Prisma model — relevant as conflict evidence): `admin\admin.controller.ts:410-441`, `admin\admin.service.ts:628-659`, `admin\admin.repository.ts:432-433` (`getBrands()` also hard-sorts `orderBy: { name: 'asc' }` — no order column exists to do otherwise)

### Mobile (`apps\mobile\src`)
- API client: `services\brandsApi.ts:1-27` (`brandsApi.getBrands()` → `GET /brands`; maps `RawBrand {id,name,slug,logo,itemCount}` down to app `Brand {id,name,itemCount}`; `getBrandById()` is a client-side filter over the same call — **no `/brands/:id` route exists backend-side**)
- Type: `types\domain.ts:26-30` (`Brand` — only `id, name, itemCount`)
- Call sites (guest/buyer/seller, at least 8 distinct screens):
  - `screens\guest\Explore.tsx:101` — guest/home "Shop by brand" taster rail (first 6, `TAXONOMY_RAIL_LIMIT`)
  - `screens\guest\BrandListing.tsx:40` — guest "view all brands" directory
  - `screens\home\BrandPage.tsx:114` — brand tap-through detail (via `getBrandById`), reachable signed-in and guest
  - `screens\search\SearchLanding.tsx:73-74` — search landing, displays `itemCount`
  - `screens\modals\Filters.tsx:201` — filter sheet, shared buyer/seller search surfaces
  - `screens\profile\PrefBrands.tsx:46-47` — buyer/seller profile brand preferences
  - `screens\auth\setup\Brands.tsx:41-42` — onboarding "brands you love" step (any new account)
  - `screens\sell\SellAIReview.tsx:248`, `screens\sell\SellFieldSheet.tsx:144` — seller sell-flow brand field picker
- Tests: `services\__tests__\brandsApi.test.ts` (URL/method, raw→domain mapping confirming `slug`/`logo` drop, empty array, network-error handling)

### Web (`apps\web\src`)
- **No call site found for plain `GET /brands`.** Admin taxonomy page uses a different endpoint entirely: `lib\api.ts:372-373` (`getBrands()` → `GET /admin/taxonomy/brands`), consumed by `app\admin\taxonomy\page.tsx`. Confirmed by searching all of `apps/web/src` for `/brands`, `getBrands`, `BrandsApi`, `useBrands` (case-insensitive) — only the 6 admin-taxonomy files matched, all hitting the different endpoint.

### Docs
- `docs\features\brand-drill-down.md` (BRI-406/BRI-407) — states an ordering expectation ("admin's own insertion order") that conflicts with the code (Finding #1).

---

## Declared Contract

**Code (controller + service):**
- **Method/Path:** `GET /brands` — no global API prefix is set in `main.ts` (`.addServer('/api')` is Swagger-doc metadata only, not an actual `setGlobalPrefix`), so the live path is `/brands`, matching the sheet and spec exactly.
- **Params:** none (path, query, header) — zero input.
- **Body:** none (GET).
- **Auth:** none — no `@UseGuards`, no role decorator on `BrandsController`; only the global `ThrottlerGuard` (100 req/min/IP) applies. Confirmed intentionally public (`brand-drill-down.md`: "no auth surface ... reachable by a guest by design").
- **Response (actual):** array of `{ id, name, slug, logo, navigationTab, createdAt, itemCount }` — full `Brand` model fields plus computed `itemCount` (live-listing count via `LIVE_LISTING_WHERE`).
- **Ordering:** `orderBy: { name: 'asc' }` (alphabetical) — see Findings #1/#2 for the conflict with app/doc expectations.

**OpenAPI spec (`schemathesis\spec\openapi.json`, operationId `BrandsController_findAll`):**
- `"/brands":{"get":{"operationId":"BrandsController_findAll","summary":"List all brands","parameters":[],"responses":{"200":{"description":""}},"tags":["Brands"]}}`
- **No response schema at all**, no other status code documented (no 5xx, no 429), no security scheme listed.

**Conflict/gap:** Spec documents nothing to validate field content or error paths against. Code and spec agree on there being zero input params and a public, unguarded route.

---

## Findings

| # | Item | Kind | Category | Evidence (file:line) | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | Backend returns brands alphabetically (`orderBy: { name: 'asc' }`), but app doc/code comments explicitly assume `GET /brands` returns "the admin's own insertion order," and Explore's "first 6" taster depends on that curated order | business-rule / ordering | **Conflict** (requirement vs. code) | Backend: `brands.repository.ts:14`; App assumption: `Explore.tsx:52-55` ("in the admin-configured order the API already returns them in — not alphabetical"), `BrandListing.tsx:26-29` ("`GET /brands` returns the admin's own insertion order"), doc: `docs\features\brand-drill-down.md:16` | Affects guest/buyer Explore taster rail | high |
| 2 | No DB column backs "admin-configured brand order" at all — `Brand` has no `sortOrder`/`order` field (unlike `Material`, which has one plus a `PUT taxonomy/materials/order` endpoint); the admin CRUD read also hard-orders alphabetically | business-rule / schema gap | **Conflict** | `schema.prisma:514-524` (no order field); `admin.repository.ts:432-433` | Backend-wide (both public and admin brand reads) | high |
| 3 | `slug`, `logo` are declared in the app's `RawBrand` type (explicitly fetched/typed) but dropped in the very next line and never reach any screen or the app's `Brand` domain type | response field | Dead field (app-side) | `brandsApi.ts:4-15` (`RawBrand` has `slug`,`logo`; `.map` keeps only `id,name,itemCount`); `types\domain.ts:26-30` (`Brand` has neither) | Unused anywhere in the mobile app (entire client checked) | high |
| 4 | `navigationTab`, `createdAt` are sent by the backend (full `Brand` row) but the app's `RawBrand` type doesn't even declare them | response field | Dead field | Backend: `brands.repository.ts:22` (`...brand` spread includes both); App: `brandsApi.ts:4-10` (no mention) | Unused anywhere found in mobile app | high |
| 5 | `BrandsRepository.findAll()` — the actual method backing this endpoint — has **no unit test**; `brands.repository.spec.ts` only covers `findNavigationTabBrands()` | existing test gap | Under-tested live path | `brands.repository.spec.ts:1-27` (no `describe('findAll'`)) vs `brands.repository.ts:12-23` | Whole endpoint | high |
| 6 | `itemCount` is read/displayed in `SearchLanding.tsx:243` but no display use was found via grep in `Explore.tsx`, `Filters.tsx`, `BrandListing.tsx` (still passed through as data, not necessarily unused) | response field | Possibly partial use | `SearchLanding.tsx:243` reads it; no `itemCount` token found in the other three files | Read only confirmed in Search flow | medium — needs a targeted read of full render JSX before asserting dead in Explore/Filters/BrandListing |
| 7 | `findById()` / `findNavigationTabBrands()` on the shared `BrandsService`/`BrandsRepository` are never routed by `BrandsController` (only `findAll()` has a route) | file/branch | Not dead — used via other services, not via this endpoint | `brands.controller.ts:11-14` (only `findAll` routed); called directly by `listings.service.ts:374`, `saved-searches.service.ts:78`, `embeddings\brand-centroid-cache.service.ts:75`, `embeddings\visual-classification.service.ts:295` | Out of scope for EP-032; noted to avoid miscounting as dead code | high |

### Looks unused but keep (and why)
- `BrandsService.findById` / `findNavigationTabBrands` — not reachable through `GET /brands`, but actively used elsewhere (Finding #7). Keep; out of scope for this endpoint.
- Global `CacheModule` registration (`app.module.ts:60-64`) — not applied to `BrandsController` (no `CacheInterceptor`/`@CacheKey` here), so there is no caching behavior to test on this route; mentioned only to rule it out.

### Could not verify (and what was checked)
- Whether `Filters.tsx` and `BrandListing.tsx` display `itemCount` anywhere in JSX beyond passing the array through — grep for the literal token `itemCount` found no hits in those two files, but a destructured/renamed variable would not show up this way. Recommend a targeted read of the full render function before asserting these as fully unused.
- Git history for `brands.repository.ts:14` (`orderBy: { name: 'asc' }`) to determine whether this predates or postdates `brand-drill-down.md` — no git tooling available in this audit; recorded as an unresolved conflict rather than guessed.
- Any seller-web or admin-web screen reaching plain `GET /brands` (as opposed to `/admin/taxonomy/brands`) — searched all of `apps/web/src` (case-insensitive) for `/brands`, `getBrands`, `BrandsApi`, `useBrands`; only the 6 admin-taxonomy files matched, all hitting the different endpoint. Treated as "no web call site" with high confidence.

---

## Sheet Check

- **Method/Path:** Sheet says `GET /brands`. Code and OpenAPI spec both confirm `GET /brands`, no prefix mismatch. **Match.**
- **Used in App? = YES:** Confirmed, with real call sites in `apps/mobile` (8+ screens). **No call site found in `apps/web`** — the admin/seller web app uses a different endpoint (`/admin/taxonomy/brands`), not this one. "Used in App" should not be read as "used in both clients" for this row.
- **Usage Note "Flow 2, 6":** No flow-name legend exists in the CSV or docs (same gap already noted in `audits\EP-038.md`), so flow numbers cannot be mapped to screen names with certainty. However, the number of distinct real call sites found — guest Explore taster, guest Brand directory "view all", guest/buyer Brand tap-through page, Search landing, Filter sheet (shared buyer/seller search), Profile brand preferences, onboarding "brands you love" step, and two separate seller sell-flow screens — is at least 8 distinct screens across guest, buyer, and seller roles, markedly broader than two numbered flows. **Likely mismatch** — "Flow 2, 6" appears to under-represent the real call-site footprint, but this cannot be stated as a certain mismatch without a flow-name legend. Flagged for clarification, not resolved.
- **Behavioral claim:** The sheet title ("Brands Controller find All") makes no behavioral claim to check against — unlike EP-038, there is no stated expected-behavior mismatch from the sheet itself. The conflict here originates from app code comments and a feature doc, not the sheet row.

---

## Test design inputs

**a. Roles and permissions**
- Anonymous/guest, buyer, seller, admin (via mobile app token if logged in) — all allowed identically. No guard enforces a role; only the global `ThrottlerGuard` (100 req/min/IP, `app.module.ts:59,104`) applies, with no per-route override for `/brands`.
- No 401/403 path exists. A request with no `Authorization` header succeeds (confirmed by doc: "no auth surface ... reachable by a guest by design").

**b. Ownership rules**
- Not applicable — brands are global catalogue data, no per-user ownership.

**c. Resource states and visibility rules**
- `Brand` itself has no status/visibility field (no draft/active/deleted states). The only "state" affecting response content is **listing** state feeding `itemCount`: a brand with zero live listings still appears with `itemCount: 0` — no filtering of brands with no stock (`brands.repository.ts:12-23`, no `where` filter excluding brands; confirmed by mobile test fixture `brandsApi.test.ts:15` using `itemCount: 0`).
- `itemCount` excludes: soft-deleted listings, `draft`/`pending_approval`/`rejected`/`inactive`/other non-`approved|active` statuses, and listings whose seller has `deletionScheduledFor` set (mid-account-deletion) — per `LIVE_LISTING_WHERE` (`listing.constants.ts:80-92`).
- No pagination; no filtering by `navigationTab` on this endpoint (that's the separate, unrouted `findNavigationTabBrands` method).

**d. Validation and error paths**
- No input to validate (zero params). Only realistically reachable error path: a DB/Prisma failure → whatever `AllExceptionsFilter` (`main.ts:52`) formats as a 5xx — not documented in the spec at all (spec only documents 200).
- Rate-limit (429) from the global throttler is a real, testable path (100 req/min/IP) but undocumented in OpenAPI.

**e. Response contract**
- Fields actually returned: `id, name, slug, logo, navigationTab, createdAt, itemCount`. OpenAPI declares **no schema whatsoever** for the 200 response — every field here is a contract gap vs. spec.
- App-side: only `id`, `name`, `itemCount` are modeled/read (`types\domain.ts:26-30`); `slug`, `logo`, `navigationTab`, `createdAt` are unused (Findings #3, #4).
- Nullability: `logo` is nullable (`String?` in Prisma) — confirmed exercised in mobile test fixture (`brandsApi.test.ts:14`, `logo: null`).

**f. Business logic / side effects**
- Read-only, no side effects, no idempotency concerns, no notifications.
- The alphabetical-ordering-vs-"admin order" discrepancy (Findings #1/#2) is the one business-rule nuance with real product impact: Explore's "first 6 brands" taster is meant (per doc) to surface admin-curated brands, but in practice will always surface the first 6 alphabetically.

**g. Existing tests and docs**
- `brands.service.spec.ts:24-35` — covers `findAll()` delegation and empty-array case at the service layer (mocked repository), asserts `itemCount` passes through unchanged.
- `brands.repository.spec.ts` — covers only `findNavigationTabBrands()`, NOT `findAll()` (Finding #5) — the live-listing join/ordering logic actually backing this endpoint has zero repository-level test coverage.
- `apps\mobile\src\services\__tests__\brandsApi.test.ts` — covers URL/method, raw→domain mapping (confirms `slug`/`logo` are dropped), empty array, and network-error → `{status:0}` rejection.
- `docs\features\brand-drill-down.md` — the ordering-expectation doc in conflict with code (Finding #1).

**h. Fixtures/accounts needed**
- No auth fixture strictly required (public endpoint) — but a token for each role (guest/none, buyer, seller) is useful to confirm identical response regardless of role.
- At least one brand with `itemCount: 0` (no live listings) and one with `itemCount > 0`.
- A brand whose only listings are in non-live states (`draft`, `sold`, soft-deleted, or seller mid-deletion) to assert `itemCount` correctly excludes them.
- Enough brands (>6) to exercise Explore's `TAXONOMY_RAIL_LIMIT = 6` slice and confirm/refute the ordering conflict.

---

## Source agreement matrix

| Behaviour | Requirement/sheet | OpenAPI spec | Code (file:line) | Existing tests | Verdict |
|---|---|---|---|---|---|
| Method/path | `GET /brands` | `GET /brands` | `brands.controller.ts:6,11` | — | Agree |
| Auth required | Sheet gives no auth requirement; docs say public | No security scheme listed for this op | No guard on `BrandsController` | — | Agree |
| Response ordering | Sheet silent; `brand-drill-down.md:16` and in-app comments say "admin's own insertion order" | No schema/ordering documented at all | `brands.repository.ts:14`: `orderBy: { name: 'asc' }` (alphabetical) | No test asserts `findAll()` ordering | **Conflict** — doc/app-comment claim vs. actual code; cannot state expected order with confidence until clarified |
| Admin-configurable brand order exists | Implied by app doc ("admin-configured order") | n/a | No `sortOrder`/`order` column on `Brand` model (`schema.prisma:514-524`); admin read also sorts alphabetically (`admin.repository.ts:432-433`) | — | **Conflict** — the premise behind the app's design doc appears unsupported by the data model |
| Response schema (fields) | Sheet gives no field list | **Spec-gap**: 200 has empty description, no schema | Returns `id,name,slug,logo,navigationTab,createdAt,itemCount` | `brands.service.spec.ts` asserts shape only via mock fixtures | **Spec-gap** — OpenAPI documents nothing to validate against |
| `itemCount` definition (live listings only) | Sheet silent | n/a | `LIVE_LISTING_WHERE` (`listing.constants.ts:89-92`) applied in `brands.repository.ts:17` | No repository test for `findAll()` | Unspecified-in-requirement — code-evidenced only, not confirmed by any requirement source |
| Error responses (5xx, 429) | Sheet silent | Only 200 documented | `AllExceptionsFilter` (`main.ts:52`), global `ThrottlerGuard` (`app.module.ts:59,104`) | None found | Spec-gap |

---

## Suggested test scenarios

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fetch brand list with no auth header | Guest/anon | n/a | Normal catalogue | 200 | Array of brand objects returned, no auth error | OpenAPI spec + Code | Confirmed | Status-only | None |
| 2 | Fetch brand list as a logged-in buyer/seller/admin token | Buyer, Seller, Admin | n/a | Normal catalogue | 200 | Identical shape/content to anonymous call (no role-based filtering) | Code (no guard) | Confirmed | Response-content | Valid JWT per role |
| 3 | Verify every returned brand's `itemCount` equals the count of its `approved`/`active`, non-deleted, non-mid-deletion-seller listings | Any | n/a | Brand with mixed listing statuses (draft, sold, soft-deleted, active) | 200 | `itemCount` matches only live listings per `LIVE_LISTING_WHERE` | Backend code | Confirmed (code-evidenced; no doc states this explicitly) | Business-rule | Fixture: brand with listings in each status + a leaving seller |
| 4 | Verify brands with zero live listings still appear (`itemCount: 0`), not filtered out | Any | n/a | Brand with only draft/sold listings | 200 | Brand present in array with `itemCount: 0` | Code + mobile test fixture | Confirmed | Response-content | Fixture: zero-listing brand |
| 5 | Verify response ordering — admin-curated/insertion order, or alphabetical by `name`? | Any | n/a | ≥7 brands, insertion order deliberately different from alphabetical | Unclear — code says alphabetical, doc says insertion order | Assert actual order; flag discrepancy against `brand-drill-down.md` | **Conflict** (Code vs. Doc) | Conflict | Business-rule | Needs product/dev clarification before an "expected" order can be asserted |
| 6 | Confirm no `/brands/:id` route exists | Any | n/a | `GET /brands/{anyId}` | 404 (likely, unmatched route) | No route match | Code comment (`brandsApi.ts:19-21`: "API currently exposes only GET /brands") | Confirmed | Status-only | None |
| 7 | Response field coverage — confirm `slug`, `logo`, `navigationTab`, `createdAt` present in raw HTTP response even though the mobile app never reads them | Any | n/a | Normal catalogue | 200 | All 7 fields present in body | Code | Confirmed | Contract | None; no spec schema to diff against (spec-gap) |
| 8 | Rate-limit behavior — exceed 100 req/min from one IP | Anon | n/a | Burst of >100 requests/min | 429 | Standard Nest throttler error body | Code (`app.module.ts:59`) | Confirmed | Status-only | Needs scripted burst, not single Schemathesis case |
| 9 | Unexpected query param sent to `GET /brands` | Any | n/a | `?foo=bar`, `?navigationTab=true` | 200 (likely ignored) | Confirm param is silently ignored, no 400 | QA suggestion | Assumed | Security/Contract | None |
| 10 | Malformed/injection-style junk on an endpoint with no query params | Any | n/a | `?id=' OR 1=1--` etc. | 200, unaffected | Confirm no error, no data leak, array unchanged | QA suggestion | Assumed | Security | None |
| 11 | Explore "first 6" taster shows the same 6 brands regardless of catalog size (business rule from doc) | Guest | n/a | >6 brands seeded | Currently: alphabetical first 6 (code) vs. doc's intended curated first 6 | Document actual vs. intended; do not assert a specific order as "pass" without clarification | Conflict (Doc vs. Code) | Conflict | Business-rule | Needs product clarification; mobile UI test, not Schemathesis |
| 12 | Cross-reference: admin-side brand deletion guard doesn't break this endpoint | Admin (separate endpoint) + Any (this endpoint) | n/a | Brand still referenced by listings | Admin op: 409; `GET /brands`: 200, brand still listed | Confirms EP-032 is unaffected by the guarded delete | Code (`admin.service.ts:648-659`) | Confirmed | Business-rule (cross-endpoint) | Out of strict EP-032 scope — context only |

---

## Summary

- 0 unused request params/items (zero request items declared at all).
- 4 unused/under-used response fields: `slug`, `logo` dropped by the mobile mapper; `navigationTab`, `createdAt` not even typed by mobile.
- 1 note (not a defect): `findById`/`findNavigationTabBrands` not reachable via this route, but actively used elsewhere — correctly out of scope, not double-counted as dead code.
- 2 conflicts recorded: the ordering-expectation doc/app-comments vs. actual alphabetical code, and the "admin-configurable order" premise vs. the absent DB column to support it.
- 1 coverage note: "Flow 2, 6" likely under-represents the real call-site footprint (8+ distinct mobile screens across guest/buyer/seller; no web call site at all).
- 1 test-coverage gap: `BrandsRepository.findAll()` — the method actually backing this endpoint — has no dedicated unit test.
- 12 suggested test scenarios (see table above).

**Primary finding:** the endpoint is correctly wired, public-by-design, and genuinely used across a broad mobile footprint, but its real-world behavior (alphabetical ordering) contradicts what app code comments and a feature doc assume it does ("admin-curated order") — and the data model has no mechanism to support the doc's assumption at all. This is a requirement/code conflict to flag to QA/PO, not resolved here per instructions.
