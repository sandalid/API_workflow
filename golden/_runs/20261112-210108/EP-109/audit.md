# Endpoint #109 - GET /sellers/me

Headline: the sheet Title assumes a suspended seller can load `GET /sellers/me` and see a "suspended" status. In the code a suspended user is rejected with 401 "Account suspended." before the handler runs. The response also has no suspended field. This is a requirement-versus-code conflict, so the expected result for the Title scenario is untrustworthy until someone clarifies it.

This is a reduced-depth audit. I did not read the full OpenAPI schema section beyond this operation, the full KB sections, the admin suspend flow, or per-field UI reads. Counts are not verified.

## Files involved (file:line)
### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- `sellers\sellers.controller.ts:128` (`@Get('me')`). Guards are `JwtAuthGuard, RolesGuard` at `sellers\sellers.controller.ts:129`, `@Roles('SELLER')` at `sellers\sellers.controller.ts:130`, and the handler `getProfile` at `sellers\sellers.controller.ts:131`.
- `sellers\sellers.service.ts:495` (`getProfile`). It throws `NotFoundException` when there is no sellerProfile (`sellers\sellers.service.ts:497`).
- `sellers\sellers.repository.ts:12` (`findUserWithProfile`), which includes `sellerProfile` and `sellerBankAccount`.
- `auth\strategies\jwt.strategy.ts:42` (`Account suspended.`). The live user is loaded from the DB on every request, and a suspended user gets 401.
- `sellers\sellers.service.ts:555` (`return this.getProfile(userId)`) is a second consumer: `updateProfile` reuses the same shape.

### Tests (`D:\Redspur_Backend\redspur-droplight\apps\api`)
- `test\sellers.e2e-spec.ts:251` (non-seller gets 403) and `test\sellers.e2e-spec.ts:265` (seller gets 200 with `shopName`, `isSeller`, `city`).
- `src\sellers\sellers.service.spec.ts:754` (`getProfile` unit tests; a NotFound case is at `src\sellers\sellers.service.spec.ts:827`).
- `src\auth\strategies\jwt.strategy.spec.ts:92` (`validate() rejects suspended users`).

### Mobile (`D:\Redspur_Backend\redspur-droplight\apps\mobile\src`)
- `services\sellersApi.ts:335` (`'/sellers/me'`).
- `screens\seller\hub\useSellerProfile.ts:57`, `screens\seller\hub\useSellerDashboard.ts:237`, `screens\seller\hub\ShopDetails.tsx:66`.
- `services\apiClient.ts:268` (suspended account handling on a 401).

### Web (`D:\Redspur_Backend\redspur-droplight\apps\web\src`)
- `lib\sellerApi.ts:355` (`'/sellers/me'`).
- Callers: `app\seller\settings\page.tsx:41`, `app\seller\page.tsx:210`, `app\seller\layout.tsx:173`.

## Declared contract
- **Request:** no path params, query params, or body. `Authorization: Bearer` is required.
- **Success response (200)**, as returned at `sellers\sellers.service.ts:500-523` (`isSeller: user.isSeller`):
  - `shopName`, `shopTagline|null`, `shopLogo|null`, `phoneNumber`, `sellerCategories`, `addressLine1`, `city`, `state`, `zip`, `country`.
  - `sellerType|null`, `legalName|null`, `taxIdLast4|null`, `notifyFollowersOnNewListing`.
  - `payout` as `{accountHolderName, bankName|null, accountNumberLast4}` or null.
  - `isSeller`.
- **No `suspended` or status field** is in the returned object.
- **Errors in code:**
  - 401 for a missing or invalid token, a suspended account (`auth\strategies\jwt.strategy.ts:42`), or an ended session (`auth\strategies\jwt.strategy.ts:51`).
  - 403 for a non-SELLER role (`sellers\sellers.controller.ts:130`).
  - 404 when there is no seller profile (`sellers\sellers.service.ts:497`).
- **OpenAPI** (`schemathesis\spec\openapi.pretty.json:4656-4670`): no parameters, and only a `200` with an empty description and no schema.
  - The 401, 403 and 404 responses are undocumented.
  - There is no response schema, and no security declaration inside the operation.

## Findings
| # | Item | Kind | Category | Evidence | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | Suspended seller can never receive a profile showing suspended status. The JWT strategy returns 401 first, so the handler is unreachable for suspended users. | branch | Requirement/code conflict (no B-category fits) | `auth\strategies\jwt.strategy.ts:42` (`Account suspended.`) | backend | high |
| 2 | The response has no `suspended` field, so there is nothing for a client to display. | response | B4-adjacent (missing field) | `sellers\sellers.service.ts:500` (`return {`), `sellers\sellers.service.ts:522` (`isSeller`) | backend | high |
| 3 | TS type `SellerProfile` declares `id`, but the backend response has no `id` field. It is always undefined. | response | B4 | `apps\mobile\src\services\sellersApi.ts:41` (`id: string`), `apps\web\src\lib\sellerApi.ts:190` (`id: string`) | mobile and web types | high that the backend never returns it; low on whether any UI reads it (not checked) |
| 4 | The web `SellerProfile` type omits `sellerType`, `legalName`, `taxIdLast4`, `notifyFollowersOnNewListing` and `payout`, which the backend returns. | response | A3 (web) | `apps\web\src\lib\sellerApi.ts:189-202` (`interface SellerProfile`) | web; mobile declares them at `apps\mobile\src\services\sellersApi.ts:54-62` | med (per-field UI reads not traced) |
| 5 | The mobile client treats a 401 containing "Account suspended" as a session expiry, not a suspended-profile view. | branch | A-side (behaviour) | `apps\mobile\src\services\apiClient.ts:268`, `apps\mobile\src\services\__tests__\apiClient.refresh.test.ts:116` | mobile | med |
| 6 | There are no B1-B3 items: the endpoint takes no inputs. | | | | | |

## Looks unused but keep
- `isSeller`: `sellers\sellers.service.ts:522` (`isSeller`) is declared in both client types and asserted in the e2e test (`test\sellers.e2e-spec.ts:272`). I did not trace UI reads.
- `updateProfile` reuses the same shape (`sellers\sellers.service.ts:555`), so the shape is shared by PATCH `/sellers/profile`.

## Could not verify
- How an admin suspends a seller, and whether suspension also flips `isSeller` or role. I did not open the admin suspend code.
- Per-field UI reads in either client (A3). Only the type definitions and call sites were checked.
- The intended product behaviour for a suspended seller (for example a read-only seller hub showing a suspended banner). No requirement source was found in the files I read. I did not read `docs\` or `full-spec.md`.
- The `RolesGuard` internals. A grep for `suspended` in `common\guards\roles.guard.ts` found nothing, but that is not proof the file is the right path. I did not read the file.

## Knowledge base cross-check
- A search of `qa-knowledge\modules\sellers.md` and `qa-knowledge\business-rules.json` for `sellers/me` and `getProfile` returned no matches.
  - The KB therefore has no section for this endpoint's rules, or the grep pattern missed the heading. I could not confirm which.
- I did not consult `endpoint-inventory.json`, `flows.md` or `dependency-map.json`.
- No KB claim was relied on in this report.

## Sheet check
- **Method and path:** Match. `GET` with controller prefix `sellers` plus `me` gives `/sellers/me` (`sellers\sellers.controller.ts:50`, `sellers\sellers.controller.ts:128`). No global prefix was checked.
- **Used in App? = YES:** Match. Mobile call sites are `apps\mobile\src\services\sellersApi.ts:335` and its three screen callers; web call sites are `apps\web\src\lib\sellerApi.ts:355` and its three pages (all listed above).
- **Usage Note "Flow 16, 20":** Not verified; I did not map the flows.
- **Title:** Mismatch with the code. A suspended seller gets a 401, not a profile that reflects suspension.

## Test design inputs
### Roles and permissions
- **Anonymous:** 401.
- **Plain USER:** 403, per `sellers\sellers.controller.ts:130` and `test\sellers.e2e-spec.ts:260`.
- **SELLER:** 200.
- **Admin:** not verified.
- **Suspended SELLER:** 401, per `auth\strategies\jwt.strategy.ts:42`.

### Ownership
The endpoint is self-only. The id comes from `req.user.id` (`sellers\sellers.controller.ts:132`), so there is no way to address another user's profile.

### Resource states
- User states are active, suspended, and unsuspended after reinstatement.
- Seller states are "has sellerProfile" and "no sellerProfile" (404).
- Seller application states such as pending or confirmed are not analysed.

### Validation and error paths
- 401 (invalid token, missing `sub` at `auth\strategies\jwt.strategy.ts:37`, account not found at `auth\strategies\jwt.strategy.ts:41`, suspended at `auth\strategies\jwt.strategy.ts:42`, session ended at `auth\strategies\jwt.strategy.ts:51`).
- 403 and 404 as above. The body shape for errors was not inspected.

### Response contract
See the Declared contract section above.
- The payout block is masked to the last 4 digits (`sellers\sellers.service.ts:519`).
- `taxIdLast4` is the last 4 digits only.

### Business logic
Read-only, with no side effects.

### Existing tests
- e2e: `test\sellers.e2e-spec.ts:251` (403) and `test\sellers.e2e-spec.ts:265` (200).
- Unit: `src\sellers\sellers.service.spec.ts:754` and `src\sellers\sellers.service.spec.ts:827`.
- Suspended-user rejection is tested only in the strategy (`src\auth\strategies\jwt.strategy.spec.ts:92`), not on this endpoint.

### Fixtures needed
Check `D:\API_workflow\schemathesis\fixtures.json` for which accounts exist; I did not open it.
- An active seller token.
- A plain user token.
- A seller who is suspended after token issue (or a token minted before suspension).
- A seller user without a sellerProfile, if one can exist.

## Source agreement matrix
| Behaviour | Requirement/sheet | OpenAPI spec | Code | Existing tests | Verdict |
|---|---|---|---|---|---|
| Suspended seller's profile view shows suspended status | Title says it should reflect suspended status | Not specified (200 only, no schema) | 401 `Account suspended.` (`auth\strategies\jwt.strategy.ts:42`); no suspended field (`sellers\sellers.service.ts:500`) | The strategy rejects suspended users (`src\auth\strategies\jwt.strategy.spec.ts:92`); no endpoint-level test | **Conflict.** The expected result of the suspended scenario cannot be trusted until someone clarifies whether 401 or a 200 with a status flag is intended. |
| Active seller gets the profile | Implied | 200, no schema | `sellers\sellers.controller.ts:128` | `test\sellers.e2e-spec.ts:265` | Agree on status; the contract is a Spec-gap |
| Non-seller is rejected | Unspecified | Not documented | 403 (`sellers\sellers.controller.ts:130`) | `test\sellers.e2e-spec.ts:251` | Spec-gap (403 missing in spec) |
| 401 and 404 responses | Unspecified | Not documented | `auth\strategies\jwt.strategy.ts:42`, `sellers\sellers.service.ts:497` | `src\sellers\sellers.service.spec.ts:827` for 404 | Spec-gap |

## Suggested test scenarios
| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Suspended seller calls GET /sellers/me | Suspended SELLER | Self | Account suspended | Title implies a profile; code gives 401. Do not fix the expectation. | Whether the body shows a suspended status is the open question. Code: message "Account suspended." | Requirement vs Backend code | Conflict | Business-rule | A suspended seller account; clarification. Schemathesis cannot decide this. |
| 2 | Active seller gets own profile | SELLER | Self | Active | 200 | Contains `shopName`, `isSeller` true, `payout` masked (last 4 only), no full tax id | Existing test, Backend code | Assumed | Response-content | Seller token |
| 3 | No token | Anonymous | n/a | none | 401 | error body | Backend code | Assumed | Status-only | None. Schemathesis can run it. |
| 4 | Plain user | USER | n/a | no seller role | 403 | error body | Existing test | Assumed | Status-only | User token |
| 5 | Seller token whose account was suspended after the token was issued | Suspended SELLER | Self | Old valid token | 401 (live DB lookup) | message "Account suspended." | Backend code | Assumed | Security | Suspension of a fixture account |
| 6 | Reinstated seller | SELLER | Self | Suspended then unsuspended | 200 | Normal profile | QA suggestion | Assumed | Business-rule | Admin suspend and unsuspend |
| 7 | User with seller flag but no sellerProfile | SELLER | Self | no profile | 404 | message "Seller profile not found" | Backend code | Assumed | Status-only | Special fixture, if possible |
| 8 | Response contract vs spec | SELLER | Self | Active | 200 | Spec has no schema, so conformance is vacuous | OpenAPI spec | Assumed | Contract | A response schema must be added to the spec |
| 9 | Injection or odd input: extra query params, malformed Bearer | Any | n/a | `?suspended=true`, bad token | 200 (params ignored) or 401 | No behaviour change from query params | QA suggestion | Assumed | Security | Schemathesis can run it |

## Summary: 0 unused request items, 2 unused or phantom response fields (TS `id` never returned; web type omits 5 backend fields), 0 dead files/branches, 1 conflict (suspended-seller profile view), 9 suggested scenarios (counts not verified)
