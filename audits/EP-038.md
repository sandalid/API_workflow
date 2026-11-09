# EP-038 Audit — GET /listings/:id

**Module:** Listings
**Method:** GET
**Path:** `/listings/:id`
**Title:** Listings Controller find By Id - Verify a draft or removed listing is not visible to any user other than its owner or an Admin.
**Used in App?:** YES
**Usage Note (sheet):** Flow 3, 18, 26

---

## Summary

The route exists and is wired end-to-end (controller → service → repository → response mapper), and it is genuinely called from both mobile and web across the three flows the sheet claims (3, 18, 26), plus several additional mobile call sites the sheet's Usage Note omits. However, the endpoint's **stated test purpose does not match its implementation**: only `pending_approval` is actually hidden from non-owner/non-admin viewers. `draft`, `rejected`, and `inactive` listings are returned in full (seller identity, price, photos) to **any** anonymous or buyer caller — explicit, tested, intentional behavior (BRI-44), not a bug, but it directly contradicts the row title. There is also no `removed` status in the domain; the nearest concept (soft-delete) hides the listing from literally everyone, including the owner and an Admin — a different (stricter) behavior than "hidden from non-owners."

---

## Files Involved

### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `listings\listings.controller.ts:373-378` (`findById`), guard import `listings\listings.controller.ts:23`, no class-level guard (`:41`)
- Guard: `auth\guards\optional-jwt-auth.guard.ts:1-17` (`OptionalJwtAuthGuard` — never rejects, only populates `req.user` if a valid token is present)
- Service: `listings\listings.service.ts:769-791` (`ListingsService.findById`)
- Visibility constants: `listings\listings.service.ts:45-63` (`LIVE_STATUSES`, `HIDDEN_FROM_PUBLIC_STATUS = 'pending_approval'`, `DELIST_STATUSES`)
- Response mapper: `listings\listings.service.ts:240-306` (`toListingDto`), `:215-232` (`mapSeller`), `:234-238` (`mapStatus`)
- Repository: `listings\listings.repository.ts:689-704` (`findById`, `findFirst` + `NOT_DELETED`)
- Soft-delete constants: `listings\listing.constants.ts:60-92` (`NOT_DELETED`, `LIVE_LISTING_WHERE`, `INDEXABLE_LISTING_WHERE`, `SELLER_NOT_LEAVING`)
- Schema: `prisma\schema.prisma:36-45` (`ListingStatus` enum: `draft, active, pending_approval, approved, rejected, inactive, sold, reserved` — no `removed` value exists)
- Tests documenting intended behavior: `listings\listings.service.spec.ts:909-1008` (`describe('findById', …)`)
- Domain doc: `docs\domain.md:53-78` (Listing states section — BRI-44/BRI-366/BRI-636 context)

### Mobile (`apps\mobile\src`)
- API client: `services\listingsApi.ts:54-78` (`ListingDto`), `:302-308` (`getListing`)
- Store: `store\productsStore.ts:220-237` (`fetchListing`)
- Shared type: `types\domain.ts:50-101` (`Product`)
- Client-side "unavailable" logic (does NOT 404, only disables buy actions): `utils\listingState.ts`
- Call sites:
  - `screens\home\ProductDetail.tsx:259,278` — buyer product detail page (Flow 3)
  - `screens\profile\SellerListingDetail.tsx:89` — seller's own listing management screen, token passed (Flow 18)
  - `screens\profile\SellerEditPrice.tsx:61` — seller edit-price screen, token passed (Flow 18)
  - `screens\profile\SellerListingStatus.tsx:36` — seller listing status screen, token passed (Flow 18)
  - `screens\profile\ResumeDraft.tsx:39` — seller resuming a saved draft (**no token passed** — see Finding #6) (Flow 18)
  - `screens\modals\MakeOffer.tsx:93` — Make Offer sheet, fallback fetch if listing not already in store (not in 3/18/26)
  - `screens\inbox\OfferThread.tsx:85` — item card inside an offer chat thread (not in 3/18/26)
  - `screens\seller\offers\SellerOfferDetail.tsx:85` — seller's own offer detail item card (not in 3/18/26)

### Web (`apps\web\src`)
- Admin client: `lib\api.ts:157-158` (`adminApi.getListing` → `/listings/${id}`, no `/admin` prefix)
- Admin call site: `app\admin\listings\[id]\page.tsx:61` (Flow 26)
- Admin type: `lib\types.ts:280-306` (`AdminListingDetail`)
- Seller-web client: `lib\sellerApi.ts:437-439` (`sellerApi.getListing`)
- Seller-web call site: `app\seller\listings\[id]\edit\page.tsx:84` (not in 3/18/26 — Flow-18 territory, web client)
- Seller-web type: `lib\sellerApi.ts:104-124` (`ListingDetail`)

---

## Declared Contract

**Code (controller + service):**
- **Path param:** `id` (string) — the only input, always used.
- **Query/body:** none.
- **Headers:** optional `Authorization: Bearer <jwt>` (`OptionalJwtAuthGuard` never 401s; populates `req.user = { id, role }` only when a valid token is sent).
- **Response** (`toListingDto`, cached under `listing:<id>`, shared across every caller regardless of role): `id, sellerId, title, description, brandId, categoryId, subcategoryId, typeId, attributes[], condition, priceCents, originalPriceCents, shippingCents, shippingTier, size, color, material, era, stock, currency, images[], videoUrl, tags[], likeCount, commentCount, watchersCount, ratingAvg, reviewCount, status, listingStatus, negotiable, minOfferPercent, createdAt, brand{}, category{}, seller{id,username,displayName,avatarUrl,rating,ratingCount,salesCount,followersCount,location,lastActiveAt}`.
- **Errors:** `404 Listing not found` for (a) nonexistent id, (b) a soft-deleted id (`deletedAt` set) — for **anyone, including owner/admin** (`listings.repository.ts:692-704`), and (c) a `pending_approval` id viewed by anyone other than its own seller or an `ADMIN` (`listings.service.ts:786-788`).

**OpenAPI spec (`schemathesis\spec\openapi.json`, operationId `ListingsController_findById`):**
- Parameters: `{"name":"id","required":true,"in":"path","schema":{"type":"string"}}` — matches code.
- Responses: `{"200":{"description":""}}` only — **no response schema**, **no 404 documented**, **no other status documented**.
- No `security` field anywhere in the whole spec file (0 occurrences repo-wide) — auth/role requirements are entirely undocumented in the spec, for every endpoint, not just this one.
- No `@ApiResponse`/`@ApiBearerAuth` decorators on the controller method — matches the spec's bareness; a pattern across the whole controller, not unique to this route.

**Conflict/gap:** The spec declares no auth requirement and no 404, while the code clearly enforces optional-auth-based visibility and does throw 404 for two distinct reasons. This is a spec-gap, not a code bug — recorded, not resolved.

---

## Findings

| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | Visibility gate only blocks `pending_approval`; `draft`, `rejected`, `inactive` are returned in full (seller identity, price, photos) to any anonymous/buyer caller | branch/auth | Dead branch relative to sheet's stated spec | `listings.service.ts:786` (`result.listingStatus === HIDDEN_FROM_PUBLIC_STATUS`, constant = `'pending_approval'` only at `:60`); explicitly asserted by `listings.service.spec.ts:965-972` (`it.each(['draft','rejected','inactive'])`, "only pending_approval is hidden"); corroborated by `docs/domain.md:70` (BRI-44 settles "page reachable, Buy Now/Make Offer disabled" as the intended non-gated behavior) | Deliberate, tested, documented backend-wide behavior | high |
| 2 | No `removed` status exists in the domain. A soft-deleted listing (`deletedAt` set) 404s for **everyone including the owner and an Admin** — stricter/opposite asymmetry from "hidden from non-owners" | query/branch | Mismatch vs sheet's stated intent | `listings.repository.ts:692-704` (`findFirst({ where: { id, ...NOT_DELETED } })`); `listing.constants.ts:60-68`; `docs/domain.md:75`; admin web hits this same public route (`lib\api.ts:157-158`) so a deleted listing is unreachable there too | Backend-wide | high |
| 3 | `ratingAvg`/`reviewCount` (top-level listing fields, denormalized on the `Listing` row, maintained by `reviews.repository.ts:137`) set on this DTO but never read by any client off this endpoint | response field | Dead field (for this endpoint) | Set at `listings.service.ts:291-292`. Not declared on mobile `ListingDto`/`Product` (`types\domain.ts:50-101`); not on `AdminListingDetail` (`lib\types.ts:280-306`) or seller-web `ListingDetail`. The only live `ratingAvg`/`reviewCount` reads in web (`app\seller\reviews\page.tsx:326-327`) come from the reviews endpoint's own DTO, a different call | Unused in all apps checked, for this endpoint specifically | medium (shared serializer, cache-manager `any` cast) |
| 4 | `watchersCount` (mirrors `likeCount`, from `_count.likes`) unused for this endpoint | response field | Dead field | Declared on mobile `ListingDto` (`listingsApi.ts:62`) but no `.watchersCount` read anywhere in production mobile code (only test files reference it, e.g. `SellerListingDetailViews.test.tsx:109`). The "Watchers" stat shown in `SellerListingDetail.tsx:68,322` is populated by the **separate** `GET /listings/:id/watchers`/views flow (`listings.controller.ts:358-367`, `getViewsCount`), not this response | Unused for this field specifically | medium |
| 5 | `likeCount`/`commentCount` required on `Product` type but no production-code read off a listing object confirmed anywhere | response field | Dead field (shared type) | `types\domain.ts:76-77` require them; grep for `.likeCount`/`.commentCount` outside `__tests__` directories returns zero hits | Shared with `toListingListDto` (browse/search/feed uses the same `Product` shape) — not unique to this endpoint | medium |
| 6 | `ResumeDraft.tsx` calls `getListing(listingId)` with **no auth token**, relying on `draft` staying ungated (Finding #1) | client / latent-bug risk | Available auth capability the caller doesn't use | `screens\profile\ResumeDraft.tsx:31,39` — `token` is read from `useAuth` but never passed to `getListing`, unlike `SellerListingDetail.tsx:89`, `SellerListingStatus.tsx:36`, `SellerEditPrice.tsx:61`, which do pass it | If `draft` is ever folded into `HIDDEN_FROM_PUBLIC_STATUS`, this screen 404s for the owner with no fallback/retry UI (`.catch(() => setListing(null))` silently blanks the screen) | high |
| 7 | Mobile call sites not captured by the sheet's "Flow 3, 18, 26" | client coverage | Undeclared flow | `MakeOffer.tsx:93`, `OfferThread.tsx:85`, `SellerOfferDetail.tsx:85` all call `fetchListing` to render an item card inside the Offers/chat flow | Additional real call sites, same endpoint | medium (no flow-name legend exists in the CSV/docs to rule out these already being folded into 3/18) |
| 8 | Seller-web edit page not captured by the sheet's three flows | client coverage | Undeclared flow | `app\seller\listings\[id]\edit\page.tsx:84` (`sellerApi.getListing`) | Real call site, Flow-18 territory but on the web client — mobile-only framing of Flow 18 misses it | high |
| 9 | OpenAPI spec documents no 404, no response schema, and no auth/security requirement for this operation at all | response/contract | Spec-gap | `ListingsController_findById` operation in `openapi.json`: `"responses":{"200":{"description":""}}` only; 0 `"security"` occurrences repo-wide in the spec | Spec-wide pattern (every endpoint in this snapshot is this sparse), not unique to EP-038 | high |

### Looks unused but keep (and why)
- `negotiable`, `minOfferPercent` — live reads: `ProductDetail.tsx:360` (`listing?.negotiable !== false`), `MakeOffer.tsx` (floor display).
- `attributes[]` — feeds the seller edit/resume form (`SellerEditPrice`/`ResumeDraft` draft-loading).
- `shippingTier`, `videoUrl`, `stock`, `subcategoryId`, `typeId` — each tied to a specific seller edit/resume screen consumer, confirmed in the grep trail.
- `offerCount` is deliberately absent from this DTO (BRI-54) — confirmed by `listings.service.spec.ts:945-949` and `web/lib/types.ts:63-65` comment. Not a finding; intentional omission.

### Could not verify (and what was checked)
- Whether any feed-adjacent component reads `ratingAvg`/`reviewCount`/`watchersCount`/`likeCount`/`commentCount` via a generic spread/render-prop rather than a named property access — checked with direct grep for `.fieldName` usage outside test directories; none found, but a dynamic-key/spread consumer would not show up this way. Lowers confidence on Findings #3-5 to medium.
- Whether the sheet's "Flow 3/18/26" numeric labels already implicitly cover the Offers-flow item-card fetches (`MakeOffer`/`OfferThread`/`SellerOfferDetail`) under a broader flow umbrella — no flow-name legend found in the CSV or docs to confirm either way.
- Exhaustive confirmation that no admin-web listing list screen can surface a soft-deleted id for an admin to click into — spot-checked the `NOT_DELETED`/`LIVE_LISTING_WHERE` pattern per `docs/domain.md:75`, not exhaustively re-walked for every admin query path.
- Whether a dedicated e2e spec exists for `GET /listings/:id` beyond the unit-level `listings.service.spec.ts` — searched `apps\api\test` for a `listings*.e2e*.ts` file; none found, only `offers.e2e-spec.ts` touches `findById` indirectly via offers fixtures.

---

## Sheet Check

**Method/path:** `GET /listings/:id` ↔ `listings.controller.ts:373-378`, `@Get(':id')` under `@Controller('listings')` with no global API prefix (0 hits repo-wide for `setGlobalPrefix`/`basePath`) — **matches exactly**.

**Used in App? = YES** — correct, confirmed real call sites in both mobile and web across every role (guest/buyer, seller, admin).

**Usage Note "Flow 3, 18, 26":**
- Flow 3 (buyer-facing) ↔ `ProductDetail.tsx:259,278` via `productsStore.fetchListing` — confirmed.
- Flow 18 (seller managing own listing) ↔ `SellerListingDetail.tsx:89`, `SellerEditPrice.tsx:61`, `SellerListingStatus.tsx:36`, `ResumeDraft.tsx:39` (mobile) — confirmed — **and additionally** `apps\web\src\app\seller\listings\[id]\edit\page.tsx:84` (seller web), not captured by a mobile-only framing of Flow 18.
- Flow 26 (Admin) ↔ `apps\web\src\app\admin\listings\[id]\page.tsx:61` — confirmed.
- **Not listed but found (re-verified, still present):** `MakeOffer.tsx:93`, `OfferThread.tsx:85`, `SellerOfferDetail.tsx:85` all call this endpoint (via `fetchListing`) to render an item card inside the Offers/chat flow — not attributable to Flow 3/18/26 with certainty absent a flow-name legend.

**Behavioral claim — Mismatch:** "Verify a draft or removed listing is not visible to any user other than its owner or an Admin" does not match the shipped code:
- `draft` (and `rejected`/`inactive`) is **not** hidden from the public on this endpoint — only `pending_approval` is gated. This is explicitly tested (`listings.service.spec.ts:961-972`) and documented as an intentional, already-settled product decision (BRI-44, per `docs/domain.md:70` and the in-code comment block at `listings.service.ts:50-59`), not an oversight.
- There is no `removed` status anywhere in the `ListingStatus` enum (`prisma\schema.prisma:36-45`). The nearest analog — soft-delete (`deletedAt`) — hides the listing from **everyone, including the owner and an Admin** (`docs/domain.md:75`, `listings.repository.ts:692-704`), the opposite asymmetry from what the row title describes ("not visible to any user **other than** its owner or an Admin" implies owner/admin CAN still see it).
- A test written literally against this row's title ("draft... not visible to any user other than owner/admin") will fail against the current, intentionally-shipped implementation on both counts.

---

## Test design inputs

**a. Roles and permissions**
- Anon/guest: allowed on `approved|active|sold|reserved|draft|rejected|inactive` (gets full DTO); 404 on `pending_approval` and soft-deleted. Guard: `OptionalJwtAuthGuard` (`optional-jwt-auth.guard.ts:13-17`) never rejects; no `RolesGuard`/`@Roles` on this route.
- Logged-in buyer (non-owner, `USER` role): identical to guest — same gate, `viewer.id !== sellerId` so `isOwner` is false; `viewer.role !== ADMIN` so `isAdmin` is false (`listings.service.ts:784-786`).
- Owner (seller of the listing): sees `pending_approval` too (`isOwner` true bypasses the gate) — but gets 404 on a soft-deleted listing of their own, same as anyone else (no owner bypass on `NOT_DELETED`).
- Admin (`Role.ADMIN`): sees `pending_approval` (`isAdmin` true bypasses the gate) — but also gets 404 on a soft-deleted listing (no admin bypass on `NOT_DELETED`). Enforced at `listings.service.ts:784-788`.

**b. Ownership rules**
- Ownership decided purely by `viewer.id === result.sellerId` string compare (`listings.service.ts:784`) — no DB-level ownership check beyond the JWT's embedded `id`.
- Cross-account access: a non-owner buyer with a `pending_approval` listing's id (from an offer thread, deep link, saved browse result, etc.) gets 404 — this is the one behavior the row title/BRI-636 does assert and the code does enforce.

**c. Resource states and visibility rules**
- `draft`, `rejected`, `inactive`, `sold`, `reserved`, `approved`, `active` — all return the full DTO to anyone (`status` flattened by `mapStatus` at `:234-238` to `available|sold|reserved` for client consumption, but `listingStatus` carries the real enum value).
- `pending_approval` — 404 unless owner/admin. Decided at `listings.service.ts:786`.
- Soft-deleted (`deletedAt` set) — 404 for literally everyone. Decided at repository level, `listings.repository.ts:692-704`, before the service's status gate even runs (listing is simply not found).
- Cache: the DTO is cached under a shared `listing:<id>` key across every viewer (`listings.service.ts:770-778`) — the status gate is re-applied on every request including cache hits (`:780-788`), confirmed by test `listings.service.spec.ts:999-1007`.

**d. Validation and error paths**
- `id`: no format validation in code (any string reaches `findFirst`); a malformed/non-existent id simply 404s via "not found," not a 400.
- Only two possible outcomes: 200 with full DTO, or 404 `{statusCode:404, message:'Listing not found'}` (Nest's default `NotFoundException` shape) — no 400/401/403/409/422/429/5xx paths observed in this handler.

**e. Response contract**
- Full field list and nullability per `toListingDto` (`listings.service.ts:240-306`) — see Declared Contract above.
- `offerCount` and `viewsCount` deliberately absent (BRI-54/BRI-319) — not a bug.
- OpenAPI spec declares no schema for the 200 response and no 404 at all — contract-level assertions cannot be schema-validated by Schemathesis against this spec as-is; only status-only checks are currently spec-backed.

**f. Business logic / side effects**
- Read-only endpoint: no mutation, no counters incremented, no notification side effects triggered by this route itself (views are tracked by a separate mechanism per `docs/domain.md:63`, not by this GET).
- Caching is the only "state": first read populates `listing:<id>`; subsequent reads (any role) hit cache but still re-run the visibility gate per request.

**g. Existing tests and docs**
- `listings.service.spec.ts:909-1008` — full `describe('findById', …)` block: returns DTO (912-917), 404 on not-found (919-922), seller-block rating/salesCount mapping (926-940), no `offerCount` (945-949), hides `pending_approval` from anon/buyer (956-959), still shows `draft|rejected|inactive` to a buyer (965-972), owner sees own `pending_approval` (974-978), admin sees `pending_approval` (980-984), `sold|reserved` always shown (986-993), cache-hit re-gate (999-1007).
- `docs\domain.md:53-78` — Listing states section; confirms BRI-44 (draft/rejected/inactive stay reachable, Buy-Now/Make-Offer disabled client-side only), BRI-366 (soft-delete hides from owner/admin's by-id reads too), BRI-636 (pending_approval gate purpose).
- No dedicated `*.e2e-spec.ts` for this route found (`apps\api\test` only has `offers.e2e-spec.ts`, which exercises `findById` only incidentally via offers fixtures, not directly).

**h. Fixtures/accounts needed**
- A listing in each status: `draft`, `pending_approval`, `approved`/`active`, `rejected`, `inactive`, `sold`, `reserved`, and one soft-deleted (`deletedAt` set).
- Owner account (the `sellerId` on each fixture) and a non-owner buyer/guest account.
- An `ADMIN`-role account.
- A valid JWT for the owner and for the admin; a request with no `Authorization` header (guest) and one with an invalid/expired token (to exercise `OptionalJwtAuthGuard`'s "never 401, just no user" path).

---

## Source agreement matrix

| Behaviour | Requirement/sheet | OpenAPI spec | Code (file:line) | Existing tests | Verdict |
|---|---|---|---|---|---|
| `draft` listing hidden from non-owner/non-admin | Sheet title says yes | No schema/status documented | `listings.service.ts:60,786` — NOT gated, only `pending_approval` is | `listings.service.spec.ts:965-972` explicitly asserts draft is NOT hidden | **Conflict** — sheet vs. code+tests+domain doc |
| `removed` listing hidden from non-owner/non-admin only | Sheet title says yes (implies owner/admin CAN see it) | N/A, no such status | No `removed` status exists (`schema.prisma:36-45`); nearest analog soft-delete hides from **everyone** (`listings.repository.ts:692-704`) | No test for a "removed" status (doesn't exist); soft-delete 404 covered indirectly by `findById` null-case test (`:919-922`) | **Conflict** — sheet's premise (a "removed" status) doesn't exist in the domain at all |
| `pending_approval` hidden from non-owner/non-admin | Not explicitly named in sheet title, but matches its spirit | Not documented | `listings.service.ts:786-788` | `listings.service.spec.ts:956-959, 974-984` | Agree (code+tests), but sheet doesn't name this status explicitly — **Unspecified-in-requirement** as to whether this is what the title meant |
| Soft-deleted listing's owner/admin access | Not addressed by sheet | Not documented | 404 for owner and admin both (`repository.ts:692-704`, `docs/domain.md:75`) | Not directly tested for owner/admin specifically (only generic null-case) | **Spec-gap** + implicit conflict with sheet's "visible to owner/admin" framing |
| Auth requirement on this route | Not addressed by sheet | **Absent** (`"responses":{"200":...}` only, 0 `"security"` entries) | `OptionalJwtAuthGuard` — optional, never 401s | N/A | **Spec-gap** |
| Response schema for 200 | Not addressed by sheet | **Absent** | Full DTO at `listings.service.ts:240-306` | Asserted field-by-field in unit tests | **Spec-gap** |
| 404 documented | Not addressed by sheet | **Absent** | Thrown in two distinct cases | Asserted in unit tests | **Spec-gap** |

---

## Suggested test scenarios

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fetch an `approved` listing | Guest (no token) | N/A | `approved` | 200 | Full DTO incl. seller block, price, images | Code | Confirmed | Response-content | Fixture id |
| 2 | Fetch a `draft` listing as a non-owner buyer | Buyer | Non-owner | `draft` | 200 (not 404) | `listingStatus: 'draft'`, full DTO still returned | Code + existing test (`:965-972`) | Confirmed-as-shipped, **Conflict with sheet title** | Business-rule | Fixture id + buyer account |
| 3 | Fetch a `rejected`/`inactive` listing as a non-owner buyer | Buyer | Non-owner | `rejected`, `inactive` | 200 (not 404) | `listingStatus` matches fixture | Code + existing test | Confirmed-as-shipped, **Conflict with sheet title** | Business-rule | Fixture id x2 |
| 4 | Fetch a `pending_approval` listing as a guest/buyer | Guest, Buyer | Non-owner | `pending_approval` | 404 | `message: 'Listing not found'` | Code + test (`:956-959`) | Confirmed | Status-only + Response-content | Fixture id |
| 5 | Fetch own `pending_approval` listing as the owner (with valid token) | Seller | Owner | `pending_approval` | 200 | `listingStatus: 'pending_approval'` returned | Code + test (`:974-978`) | Confirmed | Business-rule | Owner JWT |
| 6 | Fetch a `pending_approval` listing as Admin | Admin | N/A | `pending_approval` | 200 | Full DTO returned | Code + test (`:980-984`) | Confirmed | Business-rule | Admin JWT |
| 7 | Fetch a soft-deleted listing as its owner | Seller | Owner | `deletedAt` set | 404 | `message: 'Listing not found'` | Code + `docs/domain.md:75` | Confirmed-as-shipped, **Conflict with sheet title's "owner can see"** | Business-rule | Owner JWT + soft-deleted fixture |
| 8 | Fetch a soft-deleted listing as Admin | Admin | N/A | `deletedAt` set | 404 | `message: 'Listing not found'` | Code + `docs/domain.md:75` | Confirmed-as-shipped, **Conflict with sheet title's "admin can see"** | Business-rule | Admin JWT + soft-deleted fixture |
| 9 | Fetch a soft-deleted listing as a guest/non-owner | Guest/Buyer | Non-owner | `deletedAt` set | 404 | same | Code | Confirmed | Status-only | Fixture id |
| 10 | Fetch with a nonexistent id | Guest | N/A | random/garbage id | 404 | `message: 'Listing not found'` | Code (`:775`) | Confirmed | Status-only | None |
| 11 | Fetch a `sold`/`reserved` listing as any role | Guest, Buyer, Owner, Admin | Any | `sold`, `reserved` | 200 | `listingStatus` matches, not treated as hidden | Code + test (`:986-993`) | Confirmed | Business-rule | Fixture ids x2 |
| 12 | Cache-hit re-applies gate: fetch a now-`pending_approval` listing whose DTO is still cached from when it was live | Guest/Buyer | Non-owner | cached stale DTO, live status now `pending_approval` | 404 | 404 even though cache has the old DTO | Code + test (`:999-1007`) | Confirmed | Business-rule | Needs direct cache-manipulation or two sequential calls bridging a status change — not trivially Schemathesis-executable |
| 13 | Response does not include `offerCount` on any role | Guest, Buyer, Owner, Admin | Any | any live status | 200 | `offerCount` key absent | Existing test (`:945-949`) + `docs/domain.md`/BRI-54 | Confirmed | Contract | Fixture id |
| 14 | `ratingAvg`/`reviewCount`/`watchersCount`/`likeCount`/`commentCount` present in body but unread by clients | Any | Any | any | 200 | Fields present per schema, but note as dead weight — QA informational, not a pass/fail assertion | QA suggestion (Finding #3-5) | **Assumed** | Contract | Fixture id; confirm via static review, not Schemathesis |
| 15 | Security/odd-input: send `id` as a UUID of a different resource type (e.g. an order id) | Guest | N/A | foreign-type id string | 404 | `message: 'Listing not found'` (no 500/leak) | QA suggestion | Assumed | Negative/Security | None |
| 16 | Security: send an expired/invalid JWT (not missing) | Any | N/A | `approved` listing | 200, treated as guest (no 401) | Confirms `OptionalJwtAuthGuard` swallows errors, doesn't 401 | Code (`optional-jwt-auth.guard.ts:14-16`) | Confirmed | Security | Expired/invalid token fixture |
| 17 | Unexpected extra query params (e.g. `?include=offers`) | Guest | N/A | `approved` listing | 200, params ignored | Response unaffected by unknown query params | QA suggestion | Assumed | Negative | None |
| 18 | Sheet-title-literal scenario: "draft listing not visible to non-owner" | Buyer | Non-owner | `draft` | **Per sheet: 404. Per code: 200.** | Flag as a scenario with no trustworthy expected result until the title/code conflict is resolved by PO/QA | Sheet (conflict) | **Conflict** | Business-rule | Needs clarification before automating |
| 19 | Sheet-title-literal scenario: "removed listing visible to owner/admin only" | Owner, Admin | Owner | `deletedAt` set | **Per sheet: 200 for owner/admin. Per code: 404 for everyone.** | Same — do not automate until clarified | Sheet (conflict) | **Conflict** | Business-rule | Needs clarification before automating |

---

## Summary

- 0 unused request params (`id` is the only input, and it is used in every call path).
- 5 unused/dead response fields at medium confidence: `ratingAvg`, `reviewCount`, `watchersCount`, `likeCount`, `commentCount` (shared-DTO caveat on the latter two).
- 2 dead/mismatched auth branches relative to the stated spec: the `draft`/`rejected`/`inactive` non-gate (Finding #1), and soft-delete hiding the listing from the owner/Admin too, not just from others (Finding #2).
- 1 latent-bug risk: `ResumeDraft.tsx`'s token-less call depends on `draft` staying ungated (Finding #6).
- 2 additional real call sites/flows not captured by "Flow 3, 18, 26": the seller-web edit page (Flow 18 territory, web client) and three Offers-flow item-card fetches (`MakeOffer`, `OfferThread`, `SellerOfferDetail`).
- 4 requirement/spec/code conflicts recorded (draft-visibility, removed-status-nonexistence/soft-delete-asymmetry, and two spec-gaps: auth/security undocumented, 200/404 response schema undocumented).
- 19 suggested test scenarios (see table above).

**Primary finding:** the endpoint is correctly wired and used across all three claimed flows plus a few more, but its sheet title's behavioral claim about `draft`/`removed` visibility is false as implemented — a documented, intentional product decision in the code (BRI-44/BRI-366/BRI-636), not a bug, but it means a test written literally against the row's title will fail against the shipped behavior. Flagged to QA/PO to either correct the title or raise a product ticket; not resolved here per instructions.
