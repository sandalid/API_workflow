# Endpoint #109 - GET /sellers/me

Headline: the sheet title ("a suspended seller's own profile view clearly reflects the suspended status") cannot be met by the code I read. A suspended seller never reaches the handler, because `JwtStrategy` rejects them with 401 first. Even if they reached it, the response has no suspended or status field. No requirement source I found says what the suspended view should be, so the expected result is unclear (see Conflicts).

## Files involved
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `sellers\sellers.controller.ts:128` (`@Get('me')`) with guards at `sellers\sellers.controller.ts:129` (`@UseGuards(JwtAuthGuard, RolesGuard)`) and `sellers\sellers.controller.ts:130` (`@Roles('SELLER')`). The handler is `sellers\sellers.controller.ts:131` (`getProfile`).
- Service: `sellers\sellers.service.ts:495` (`getProfile`). It calls `this.repo.findUserWithProfile` (`sellers\sellers.service.ts:496`). I did not open the repository query.
- Suspension check: `auth\strategies\jwt.strategy.ts:42` (`Account suspended.`). It loads the live user via `findRawById` on every request (`auth\strategies\jwt.strategy.ts:40`).
- Role check: `common\guards\roles.guard.ts:43` (`findRawById`). It checks only the live `isSeller`; there is no `suspended` handling in this guard.
- Tests: `sellers\sellers.service.spec.ts:747-828` (`getProfile` unit tests) and `..\test\sellers.e2e-spec.ts:251-275` (`apps\api\test`).

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- API client: `services\sellersApi.ts:334` (`getProfile`) and type `services\sellersApi.ts:40` (`SellerProfile`).
- Hook: `screens\seller\hub\useSellerDashboard.ts:237` (`sellersApi.getProfile(token)`).
- Shared cache: `screens\seller\hub\useSellerProfile.ts:112` (`useSellerProfile`).
- Screens using the hook: `screens\seller\hub\ContactDetails.tsx:55`, `screens\seller\hub\PayoutDetails.tsx:141`, `screens\seller\hub\SellerSettings.tsx:120`. `ShopDetails.tsx` also calls this endpoint (`screens\seller\hub\ShopDetails.tsx:24` doc comment). I did not open `ShopDetails.tsx` to see how.

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- Helper: `lib\sellerApi.ts:354` (`getProfile`), type `lib\sellerApi.ts:189` (`SellerProfile`).
- Callers: `app\seller\settings\page.tsx:41`, `app\seller\page.tsx:210`, `app\seller\layout.tsx:173`.

## Declared contract
- **Request:** no path, query, header or body inputs beyond the Bearer token (`sellers\sellers.controller.ts:131`). OpenAPI declares `"parameters": []` (`schemathesis\spec\openapi.pretty.json:4660`).
- **Response, per code** (`sellers\sellers.service.ts:500-523`): `shopName`, `shopTagline|null`, `shopLogo|null`, `phoneNumber`, `sellerCategories`, `addressLine1`, `city`, `state`, `zip`, `country`, `sellerType|null`, `legalName|null`, `taxIdLast4|null`, `notifyFollowersOnNewListing`, `payout` (object or null), `isSeller`.
  - There is no `suspended` or `status` field and no `id` field in this object.
- **Errors in code:**
  - 401 when the token is missing/invalid, the account is not found, or the account is suspended (`auth\strategies\jwt.strategy.ts:41-42`).
  - 403 when the user is not a seller (`common\guards\roles.guard.ts:60`).
  - 404 when there is no seller profile (`sellers\sellers.service.ts:497`).
- **OpenAPI** (`schemathesis\spec\openapi.pretty.json:4656-4670`): documents only 200, with description `""` and no response schema. 401, 403 and 404 are undocumented.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | The response carries no suspended/status indicator, and a suspended seller never gets a 200 anyway: 401 `Account suspended.` comes first | response/branch | Contract gap vs sheet title (not B1-B5) | `auth\strategies\jwt.strategy.ts:42` (`Account suspended.`); `sellers\sellers.service.ts:500` (`return {`) | Backend | high |
| 2 | Both app `SellerProfile` types declare `id`, but the service does not return it | response | B4/A3-type mismatch | `sellers\sellers.service.ts:500` (no `id` field in the returned object); `..\mobile\src\services\sellersApi.ts:41` (`id: string;`); `..\web\src\lib\sellerApi.ts:190` (`id: string;`) | Mobile and web | high |
| 3 | Mobile type has no suspended field, and I found no suspended handling for this payload in the mobile seller hub (search of `apps\mobile\src` for "suspend" returned no seller-hub hits). The mobile client does handle a suspended 401 generically: it expires the session and does not loop. | response | A3 context | `..\mobile\src\services\apiClient.ts:268` (suspended-401 comment) | Mobile | med |
| 4 | Web `SellerProfile` omits `sellerType`, `legalName`, `taxIdLast4`, `notifyFollowersOnNewListing` and `payout`, which the API returns. Nothing in the web type reads them. | response | A3 (web) | `..\web\src\lib\sellerApi.ts:189-202` (`SellerProfile`, no `payout` field) vs `sellers\sellers.service.ts:515` (`payout:`) | Web | high (type level); I did not check web pages for untyped reads |
| 5 | `shopTagline`, `shopLogo` and `sellerCategories` are typed in both clients. I did not trace per-screen reads. | response | A3 not fully assessed | `..\mobile\src\services\sellersApi.ts:43` (`shopTagline`) | Both | low |
| 6 | The sheet's "Used in App" claim holds (YES). The path matches, with no global prefix mismatch seen. | - | - | `..\mobile\src\services\sellersApi.ts:335` (`'/sellers/me'`) | - | high |

No B1/B2/B3/B5 items: the endpoint takes no inputs.

## Looks unused but keep
- `isSeller` in the response is always `true` for anyone who passes `@Roles('SELLER')`. It is still part of the app types and is used for cache priming after PATCH (`sellers\sellers.service.ts:529-534` doc comment).
- `payout`, `sellerType`, `legalName` and `taxIdLast4` are read by mobile settings and payout screens (the typed fields exist at `..\mobile\src\services\sellersApi.ts:54` and `:62`). Web does not type them.

## Could not verify
- Whether any doc or ticket specifies how a suspended seller's profile should look. I grepped `docs\*.md` and `full-spec.md` for Flow 16/20 and found nothing relevant. I did not find a flow definition, so the sheet's "Flow 16, 20" is unconfirmed.
- Which admin or seller flow suspends the seller. Admin web calls `adminApi.suspendUser` at `..\web\src\lib\api.ts:209`.
- The `findUserWithProfile` query: whether it filters `suspended`. It is moot because the guard rejects first.
- Per-screen field reads for mobile `ShopDetails` and the `SellerSettings` rendering.
- Live behaviour: no suspended-seller account exists in the fixtures. My grep of `schemathesis\fixtures.json` for seller and role keys found only an ownership note, not a suspended account.

## Knowledge base cross-check
- `qa-knowledge\modules\sellers.md` section 9 (lines 113-117) lists the same guards and response fields. Re-verified against `sellers\sellers.controller.ts:128-133` and `sellers\sellers.service.ts:495-524`.
- The KB's response-field list has no suspended field, which agrees with the code.
- KB BR-SELLERS-008 (payout is last-4 only) is `confirmed-by-code` and stays Assumed. The code agrees: `sellers\sellers.service.ts:519` (`accountNumberLast4`).
- The KB does not mention the suspended-seller 401 for this endpoint. It is the key lead for this title and comes from `auth\strategies\jwt.strategy.ts:42`.
- The KB has no suspended-specific rule or gap for GET /sellers/me. My grep of `gaps-and-conflicts.md` for "suspend" gave only auth and messaging rows.
- I did not open the endpoint-inventory entry (line 2349), so I did not check its `status` (shallow or not).

## Sheet check
- Method and path match: `sellers\sellers.controller.ts:50` (`@Controller('sellers')`) plus `sellers\sellers.controller.ts:128`.
- "Used in App? = YES" is correct. Mobile call sites:
  - `..\mobile\src\screens\seller\hub\useSellerDashboard.ts:237`
  - `..\mobile\src\screens\seller\hub\useSellerProfile.ts:112`, used by `SellerSettings.tsx:120`, `ContactDetails.tsx:55` and `PayoutDetails.tsx:141`
  - `..\mobile\src\screens\seller\hub\ShopDetails.tsx:24`: doc comment only, call not verified
- Web call sites: `..\web\src\app\seller\settings\page.tsx:41`, `..\web\src\app\seller\page.tsx:210`, `..\web\src\app\seller\layout.tsx:173`.
- Usage Note "Flow 16, 20": unverifiable, because no flow list was found in the docs I searched.
- Title mismatch: the sheet expects a 200 view that "reflects suspended status", but the code gives a 401 to suspended users.

## Test design inputs
**Roles and permissions**
- No token: 401 from `JwtAuthGuard` (mechanism inferred; not opened).
- Non-seller user: 403 at `common\guards\roles.guard.ts:60`.
- Seller: 200.
- Suspended seller: 401 `Account suspended.` at `auth\strategies\jwt.strategy.ts:42`.
- Admin without `isSeller`: 403, because `SELLER` is checked live and the admin role is not accepted (`sellers\sellers.controller.ts:130`).

**Ownership**
- Identity comes solely from `req.user.id` (`sellers\sellers.controller.ts:132`). There is no id parameter, so no cross-account access is possible.

**Resource states**
- Seller active: 200.
- Seller suspended: 401 (JWT strategy).
- A seller whose `isSeller` is false (for example a pending application): 403.
- `isSeller` true with no profile row: 404 (`sellers\sellers.service.ts:497`).
- Account purged or deleted: `account-deletion.repository.ts:320` sets `suspended: true`, so these also get 401. This is from the cited comment at lines 318-320; I did not read it in full.

**Validation and errors**
- No inputs. Error bodies follow the Nest shape (`message`); the e2e spec only asserts the status code.

**Response contract**
- See "Declared contract". OpenAPI has no schema.
- A stale token that still carries the old `suspended: false` claim is still rejected, because the DB is re-read on every request (`auth\strategies\jwt.strategy.ts:26-33`).

**Business logic**
- Read-only, no side effects (`sellers\sellers.service.ts:495-524`).

**Existing tests**
- Unit (`sellers\sellers.service.spec.ts:747-828`): fields, onboarding nulls, masked payout, null payout, and 404 for a missing profile.
- e2e: 403 for a non-seller (`..\test\sellers.e2e-spec.ts:251`) and 200 with `shopName`, `isSeller` and `city` (`..\test\sellers.e2e-spec.ts:265`).
- Suspended-user rejection is tested only at the JWT-strategy level (`auth\strategies\jwt.strategy.spec.ts:92`). It has no test specific to this endpoint, and no test covers a suspended seller's profile view.
- Mobile jest tests cover the profile cache, and `..\mobile\src\services\__tests__\apiClient.refresh.test.ts:116` covers the suspended 401.

**Fixtures needed**
- An active seller token.
- A plain non-seller user token.
- A seller that an admin then suspends, via `PATCH /admin/users/:id/suspend` (`..\web\src\lib\api.ts:209-212`).
- An admin account.
- `fixtures.json` has none of these. I saw only an owner readme line, so a suspended-seller account and token must be created.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI | Code | Tests | Verdict |
|---|---|---|---|---|---|
| Suspended seller's own profile view reflects suspended status | Sheet title says it should show it | Silent: only 200, no schema (`schemathesis\spec\openapi.pretty.json:4662`) | Suspended seller gets 401 (`auth\strategies\jwt.strategy.ts:42`); response has no suspended field (`sellers\sellers.service.ts:500`) | None for this endpoint | Conflict: the title cannot have a trustworthy expected result until someone clarifies whether the intended behaviour is "401 means suspended" or "200 with a status field" |
| Non-seller gets 403 | Unspecified | Not documented (403 absent) | `common\guards\roles.guard.ts:60` | `..\test\sellers.e2e-spec.ts:251` | Spec-gap: undocumented but tested |
| 401 for unauthenticated or suspended | Unspecified | Not documented | `auth\strategies\jwt.strategy.ts:41` | JWT-strategy spec only | Spec-gap |
| Missing profile gives 404 | Unspecified | Not documented | `sellers\sellers.service.ts:497` | `sellers\sellers.service.spec.ts:825` | Spec-gap |
| Response shape | Unspecified | No schema | `sellers\sellers.service.ts:500-523` | Unit and e2e assert subsets | Spec-gap |
| Payout masked to last 4 | KB BR-SELLERS-008 (code-only) | Silent | `sellers\sellers.service.ts:519` | `sellers\sellers.service.spec.ts:773` | Unspecified-in-requirement |

## Suggested test scenarios
All expectations below are Assumed unless stated.

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Req. status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Suspended seller calls own profile | Seller suspended | Own | Token issued before suspension | 401 per current code (the title implies a visible suspended status; clarify) | Message `Account suspended.`; no profile body | Backend code; sheet title | Conflict | Business-rule | Suspended seller account and token |
| 2 | Same as 1 using a token obtained before suspension (stale claims) | Seller suspended | Own | Old token | 401 | Same | Backend code (`auth\strategies\jwt.strategy.ts:26-42`) | Assumed | Security | Same fixture |
| 3 | Active seller views own profile | Seller | Own | Active | 200 | Contains `shopName`, `isSeller:true`, and `payout` that is null or has only `accountNumberLast4`; no full account or routing number | Backend code | Assumed | Response-content | Seller token |
| 4 | Check for any suspended/status field in the 200 body | Seller | Own | Active | 200 | Record whether a suspended/status field exists (code: none) | Sheet title | Conflict | Contract | Seller token |
| 5 | No token | Anon | - | - | 401 | - | Backend code | Assumed | Status-only | Schemathesis can run it |
| 6 | Plain user | User | - | Not a seller | 403 | - | Existing e2e | Assumed | Status-only | User token |
| 7 | Admin token without `isSeller` | Admin | - | - | 403 | - | Backend code | Assumed | Security | Admin token |
| 8 | Unsuspended seller afterwards | Seller | Own | Restore via admin | 200 with a valid profile | - | QA suggestion | Assumed | Business-rule | Admin and seller |
| 9 | Odd input: extra query params and a body on GET | Seller | Own | `?x=1` | 200 and params ignored | - | QA suggestion | Assumed | Contract | Schemathesis with seller token |
| 10 | Seller with no profile row (data fault) | Seller | Own | Profile missing | 404 | - | Backend code | Assumed | Business-rule | DB fixture, hard to create |
| 11 | Seller who onboarded before BRI-285 | Seller | Own | Nulls in new fields | 200 | `sellerType`, `legalName` and `taxIdLast4` are null, not omitted | Unit test | Assumed | Response-content | Legacy seller |
| 12 | Pending seller application (`isSeller` false) | User | Own | Not yet confirmed | 403 | - | Backend code | Assumed | Status-only | Applicant account |

Schemathesis can run only 5, 9 and, if schemas are added, 3. The OpenAPI response schema is absent for all statuses. The remaining scenarios need a role/account fixture and manual or scripted checks.

## Summary: 0 unused request items, 1 response field the apps type but the API never returns (`id`) plus 5 API fields missing from the web type, 0 dead files/branches, 1 conflict (suspended-view requirement vs code and spec), 12 suggested scenarios
