# EP-109 Audit — GET /sellers/me

**Module:** Sellers
**Method:** GET
**Path:** `/sellers/me`
**Title:** Sellers Controller get Profile -  Verify a suspended seller's own profile view clearly reflects the suspended status.
**Used in App?:** YES
**Usage Note (sheet):** Flow 16, 20

---

## Summary

`GET /sellers/me` is correctly wired, guarded (`JwtAuthGuard` + `RolesGuard`/`@Roles('SELLER')`), and genuinely called from both mobile (Seller Hub dashboard/Settings/Shop Details) and seller-web (layout, dashboard, settings). But the row's specific behavioral claim — "a suspended seller's own profile view clearly reflects the suspended status" — **cannot be true under the shipped code, by construction**: account suspension is enforced as a global, account-level gate at the authentication layer (`JwtStrategy.validate`, `AuthService` login methods), which rejects every request from a suspended account with `401 Account suspended.` **before** the request ever reaches `SellersController`/`SellersService.getProfile()`. A suspended seller therefore can never receive a `200` from this endpoint at all — there is no "profile view" to inspect. Compounding this, even in the service method itself, `SellersService.getProfile()` reads the full `User` row (which includes `suspended`) but never maps `suspended`/`status` into its response DTO — unlike the admin-facing `getAllSellers()`/`getSellerByIdForAdmin()`, which both explicitly return `suspended`/`status: 'suspended'|'active'`. Both mobile and web additionally swallow this 401 into a generic "session expired" / "couldn't load" UX with zero suspension-specific messaging, reinforcing that the feature the sheet title describes does not exist anywhere in the current implementation.

---

## Files Involved

### Backend (`D:\Redspur_Backend\redspur-droplight\apps\api\src`)
- Route: `sellers\sellers.controller.ts:127-133` (`getProfile`), guards `:129` (`@UseGuards(JwtAuthGuard, RolesGuard)`, `@Roles('SELLER')`)
- Service: `sellers\sellers.service.ts:495-524` (`getProfile`) — reads `user.suspended` via `this.repo.findUserWithProfile(userId)` but never includes it in the returned object
- Repository: `sellers\sellers.repository.ts:12-17` (`findUserWithProfile` — unselected `prisma.user.findUnique`, returns every scalar field including `suspended`, plus `sellerProfile`/`sellerBankAccount`)
- Auth gate that actually decides this behavior (not specific to this endpoint): `auth\strategies\jwt.strategy.ts:34-62`, specifically `:42` (`if (dbUser.suspended) throw new UnauthorizedException('Account suspended.')`) — re-checked on **every** authenticated request, live from the DB, not from the JWT claim
- Guard that forwards that thrown error unchanged: `auth\guards\jwt-auth.guard.ts:11-25` (`handleRequest` re-throws `err`)
- Login-time equivalent (five call sites, same message): `auth\auth.service.ts:166-168` (password login), `:542-543` (passwordless/OTP), `:617-618` (Google), `:716-717` (Apple), `:805-806` (Facebook), `:933-935` (seller OTP-resend eligibility path)
- Role check that does **not** also check suspension (because it never needs to — suspension is already rejected upstream): `common\guards\roles.guard.ts:16-64`
- Contrast — other seller-facing/admin DTOs in the same service that DO surface `suspended`/`status`: `sellers.service.ts:1253-1285` (`getAllSellers`, admin sellers table), `:1294-1330` (`getSellerByIdForAdmin`)
- Suspension toggle (fixture mechanism): `admin\admin.controller.ts:160-165` (`PATCH /admin/users/:id/suspend`, guarded `@Roles(Role.ADMIN)` at class level `:52-54`), `admin\admin.service.ts:382-388` (`suspendUser`), `admin\admin.repository.ts:366-368` (`updateUserSuspended` — flips only the `suspended` boolean; `isSeller` is untouched)
- Schema: `prisma\schema.prisma:277` (`suspended Boolean @default(false)` on `User`), `:328` (`isSeller`) — no separate `SellerStatus` enum anywhere in the schema; suspension is account-level, not seller-specific
- Unit test confirming the auth-layer rejection (generic, not endpoint-specific): `auth\strategies\jwt.strategy.spec.ts:92-105` (`'validate() rejects suspended users'`)
- `SellersController`/`SellersService.getProfile()` has **no dedicated unit test for suspension** — `sellers.service.spec.ts:720-828` (`describe('getProfile', …)`) covers field mapping, payout masking, BRI-285 nulls, and the not-found case, but no suspended-seller scenario
- No `sellers.controller.spec.ts` exists at all (confirmed by glob — zero files)
- Doc stating the expected suspension behavior as a login-time block, not a profile-view state: `docs\manual-test-cases.md:544-551` ("Confirm suspension → User's status changes to 'Suspended'" (admin side) / "try to log in as the suspended user → Error: 'Your account has been suspended' or 'Access denied'" (mobile side)), `:778` ("Admin can suspend users")

### Mobile (`apps\mobile\src`)
- API client: `services\sellersApi.ts:40-64` (`SellerProfile` type — no `suspended`/`status` field), `:335` (`getProfile` → `GET /sellers/me`)
- Shared cache/hook: `screens\seller\hub\useSellerProfile.ts:54-74` (`startLoad` — 401 swallowed into a boolean `entry.error = true`, message discarded), `:112-147` (`useSellerProfile`)
- Call sites: `screens\seller\hub\ShopDetails.tsx:24` ("Reads `GET /sellers/me`…"), `screens\seller\hub\SellerSettings.tsx:33,115,120,165-172` (Seller Hub → Settings "Account" section; on error shows generic `"Couldn't load your account details. Reopen Settings to try again."` — `:170`), `screens\seller\hub\useSellerDashboard.ts:220,246` (dashboard batch primes the same cache)
- Global 401 handling (runs before any screen-local catch above fires): `services\apiClient.ts:260-321` — silent-refresh-and-retry, then `useAuth.getState().expireSession()` on a still-401 (comment at `:268` explicitly names "a suspended account" as the scenario this guards against)
- Test confirming the exact wire message is exercised in this retry path: `services\__tests__\apiClient.refresh.test.ts:119-124` (`jsonResponse(401, { message: 'Account suspended.' })` → `expireSession` called)
- Resulting UI after `expireSession()`: `screens\auth\SessionExpired.tsx:29-94` — generic "WELCOME BACK" / "confirm it's you" re-auth screen; **no mention of suspension anywhere in its copy**
- Login-time OTP error mapping (if the seller then tries to re-authenticate): `services\authApi.ts:169-238` (`toOtpError`) — a `401`/`'Account suspended.'` response matches none of the explicit branches (`OTP_NOT_FOUND/EXPIRED`, `OTP_LOCKED`, `OTP_COOLDOWN`, `OTP_INVALID`, `429`, `409`, `400`) and falls through to the final `return new OtpError(msg, 'wrong-code', …)` at `:236` — i.e. a suspended account's login attempt is classified identically to "wrong code" at the type level, though `msg` itself (the raw `'Account suspended.'` string) is preserved and may still reach the screen depending on `errorText` rendering in `screens\auth\OtpEntry.tsx:149-174` (not fully traced — see Could Not Verify)
- Dead/mismatched field: mobile `SellerProfile.id: string` (`services\sellersApi.ts:41`, required, non-nullable) is **never returned** by the backend's `getProfile()` (`sellers.service.ts:500-523` has no `id` key) and is never read anywhere off this endpoint's response (`grep` for `profile.id`/`sellerProfile.id` across `apps/mobile/src` found exactly one hit, `screens\home\ShopProfile.tsx:146`, which reads `.id` off `usersApi.getPublicProfile()`'s response — a **different** endpoint entirely, not this one)

### Web (`apps\web\src`)
- API client: `lib\sellerApi.ts:1-31` (shared `request` wrapper — 401 → `clearSellerAuth()` + `window.location.replace('/seller/login')`, `:22-24`), `:355` (`getProfile` → `GET /sellers/me`)
- Call sites: `app\seller\layout.tsx:161-178` (auth bootstrap — `sellerApi.getProfile().then(...).catch(() => {})` at `:173-175`, error **silently discarded**), `app\seller\page.tsx:210` (dashboard), `app\seller\settings\page.tsx:38-41` (Settings — loads `/sellers/me` + `/users/me` together)
- Seller login page/component: `app\seller\login\page.tsx:1-19` (routes to shared `UnifiedLogin`), `components\UnifiedLogin.tsx:74,145-146` (raw `err.message` IS shown verbatim on a caught login error — so on **web**, unlike mobile's OTP-kind bucketing, a suspended seller attempting to log back in after being bounced would plausibly see the literal string `"Account suspended."` on the login screen; not fully confirmed end-to-end, see Could Not Verify)
- Admin-web parallel pattern (for context, not this endpoint): `lib\api.ts:76-83` (same 401 → clear token → redirect pattern), `app\admin\sellers\page.tsx` / `app\admin\sellers\[id]\page.tsx` (these **do** display `suspended`/`status` via `getAllSellers`/`getSellerByIdForAdmin`, confirming the field exists and is rendered elsewhere, just not on this endpoint)

---

## Declared Contract

**Code (controller + service):**
- **Path/Query params:** none.
- **Headers:** `Authorization: Bearer <jwt>` — required. Guard chain: `JwtAuthGuard` (passport `AuthGuard('jwt')`, delegates to `JwtStrategy.validate`) → `RolesGuard` (`@Roles('SELLER')`, live DB check of `isSeller`).
- **Body:** none (GET).
- **Response (actual, from `getProfile`):** `{ shopName, shopTagline, shopLogo, phoneNumber, sellerCategories, addressLine1, city, state, zip, country, sellerType, legalName, taxIdLast4, notifyFollowersOnNewListing, payout: {accountHolderName, bankName, accountNumberLast4} | null, isSeller }`. **No `suspended`, no `status`, no `id` field.**
- **Errors:** `404 Seller profile not found` (`sellers.service.ts:497`) if `user.sellerProfile` is null (e.g. `isSeller: true` but onboarding incomplete — an edge case distinct from suspension); `401 Account suspended.` thrown by `JwtStrategy.validate` **before the controller runs**, for any suspended account regardless of role; `403 Insufficient permissions.` from `RolesGuard` if `isSeller` is false (live DB check, not JWT claim).

**OpenAPI spec (`schemathesis\spec\openapi.json`, operationId `SellersController_getProfile`):**
```
"/sellers/me":{"get":{"operationId":"SellersController_getProfile","summary":"Get the caller's own seller profile","parameters":[],"responses":{"200":{"description":""}},"tags":["Sellers"]}}
```
- **No response schema at all** (empty `description`, no `content`/`schema` key).
- **No 401, 403, or 404 documented.**
- **No security scheme** anywhere in the spec file (consistent with every other endpoint audited so far — a spec-wide gap, not unique to this route).

**Conflict/gap:** The spec documents zero contract detail to validate against — not the success shape, not any error status, not the auth requirement. This is a pure spec-gap; code and spec do not actively disagree because the spec says nothing to disagree with.

---

## Findings

| # | Item | Kind | Category | Evidence (file:line) | Scope | Confidence |
|---|---|---|---|---|---|---|
| 1 | **A suspended seller can never receive a 200 from this endpoint.** `JwtStrategy.validate` throws `401 Account suspended.` for any suspended account, live from the DB, before `SellersController.getProfile` ever runs | auth/branch | Dead branch relative to sheet's premise | `jwt.strategy.ts:34-42` (specifically `:42`); re-thrown unchanged by `jwt-auth.guard.ts:11-25`; unit-tested generically at `jwt.strategy.spec.ts:92-105` | Backend-wide — applies to every authenticated endpoint, not just this one | high |
| 2 | Even where `user.suspended` is already in hand inside `getProfile()` (fetched via the unselected `findUserWithProfile` query), the method never maps `suspended`/`status` into its returned DTO | response field | B1 — read (implicitly, via the Prisma object) but never surfaced | `sellers.repository.ts:12-17` (returns full `User` row incl. `suspended`); `sellers.service.ts:495-524` (return object at `:500-523` omits `suspended`/`status` entirely) | This endpoint specifically | high |
| 3 | Asymmetry: the admin-facing seller DTOs on the **same service** (`getAllSellers`, `getSellerByIdForAdmin`) DO include `suspended: boolean` and a derived `status: 'suspended'|'active'` string — proving the field is a known, modeled concept the team already surfaces elsewhere, just not on the seller's own `/me` view | response field | Contract asymmetry (not a bug per se, but directly contradicts the row title's premise that the seller's own view should show this) | `sellers.service.ts:1253-1285` (`getAllSellers`, `suspended`/`status` at `:1272-1273`), `:1294-1330` (`getSellerByIdForAdmin`, `:1311-1312`) | Admin surface only; absent from seller-self surface | high |
| 4 | Mobile `SellerProfile` type declares `id: string` (required, non-nullable) but the backend's `getProfile()` response never includes an `id` key at all | response field | Declared-but-never-sent (client-side type/contract mismatch) | Mobile: `sellersApi.ts:41`; Backend: `sellers.service.ts:500-523` (no `id` key) | Checked across all of `apps/mobile/src` — the one `profile.id` read found (`ShopProfile.tsx:146`) is off a **different** endpoint (`usersApi.getPublicProfile`), not this one | high |
| 5 | Both app clients (mobile and web) discard the specific 401 error message/body on this call, surfacing only a generic "session expired" (mobile, app-wide) or silent failure / redirect-to-login (web) — neither ever shows "suspended" to the seller even on the rare path where the error does reach a local handler | client / UX | Dead error content (error-body field never read for user-facing display) | Mobile global 401 handling: `apiClient.ts:260-321`, resulting screen `SessionExpired.tsx:29-94` (no suspension copy); mobile local catch: `useSellerProfile.ts:63-68` (boolean only) rendered as generic text at `SellerSettings.tsx:165-172`; Web: `sellerApi.ts:19-28` (redirects before the thrown `Error` with `body.message` is ever observed), `app\seller\layout.tsx:173-175` (`.catch(() => {})` — fully discarded) | Both clients, for this endpoint's 401 path specifically | medium — the exact rendering in `OtpEntry.tsx`'s `errorText` for the re-login attempt was not fully traced (see Could Not Verify) |
| 6 | `SellersController.getProfile` has no dedicated unit test and no controller spec file exists for `SellersController` at all; no e2e test exercises `GET /sellers/me` + a suspended fixture | existing test gap | Under-tested live path | `sellers.service.spec.ts:720-828` (covers everything except suspension); glob for `sellers.controller.spec.ts` → no file; `apps\api\test` suspension-related e2e only in `users-social.e2e-spec.ts` (unrelated to sellers) | Whole endpoint, suspension scenario specifically | high |
| 7 | OpenAPI spec documents no schema for 200, and no 401/403/404 at all, for this operation | response/contract | Spec-gap | `SellersController_getProfile` operation body quoted above | Spec-wide pattern, not unique to EP-109 | high |

### Looks unused but keep (and why)
- `isSeller` in the response — actively consumed logic-wise (RolesGuard re-derives it live rather than trusting this field, but the client still reads it to gate UI, per `SellerSettings.tsx`/dashboard patterns) — not a finding, just noted to avoid miscounting.
- `payout`/`taxIdLast4`/`sellerType`/`legalName` — all confirmed live-read by `ShopDetails.tsx`/`SellerSettings.tsx` per BRI-285 onboarding display logic documented in the service comment (`sellers.service.ts:482-493`). Not dead.

### Could not verify (and what was checked)
- The exact rendered `errorText` in `OtpEntry.tsx` for a `401 Account suspended.` response mapped to `OtpErrorKind: 'wrong-code'` (`authApi.ts:236`) — checked `OtpEntry.tsx:149-174` and the `errorText` computation reference at `:248`, but did not fully trace the JSX branch for `errKind === 'wrong'` to confirm whether `err.message` (the literal "Account suspended." string) or a hardcoded "That code isn't right" copy is what actually renders. This affects only the **re-login** attempt after being kicked out, not `GET /sellers/me` itself, but it is directly relevant to whether the suspended-seller journey ever surfaces the word "suspended" anywhere in the mobile app.
- Whether seller-web's `UnifiedLogin.tsx:145-146` (`setError(err.message)`) is reached for a suspended seller's **login** attempt versus being intercepted earlier by some other check — traced the error-propagation code but did not execute/mock the live login endpoint to confirm the raw string "Account suspended." is what a seller actually sees on `/seller/login`.
- Whether any other currently-undiscovered seller-self surface (e.g., a push notification, an email, an in-app banner triggered by the admin's suspend action) communicates the suspension to the seller — searched `docs/`, `admin.service.ts`, and messaging/notification service call sites around `suspendUser` and found no notification/email side effect wired to `admin.service.ts:382-388`; recorded as "not found" rather than "confirmed absent" since notification services are extensive and were not exhaustively walked.
- Whether a `sellers.controller.spec.ts` or equivalent integration test exists under a differently-named file — searched by exact filename glob only; a controller test embedded inside a differently-named spec file would not have been caught.

---

## Sheet Check

- **Method/Path:** Sheet says `GET /sellers/me`. Code: `@Controller('sellers')` + `@Get('me')` at `sellers.controller.ts:50,128` — no global prefix set (consistent with other audited endpoints). **Match.**
- **Used in App? = YES:** Confirmed — real call sites in both clients:
  - Mobile: `ShopDetails.tsx:24`, `SellerSettings.tsx:33,115,120`, `useSellerDashboard.ts:220,246` (Seller Hub Home/Settings/Shop Details).
  - Web: `app\seller\layout.tsx:173`, `app\seller\page.tsx:210`, `app\seller\settings\page.tsx:41` (Seller dashboard, layout bootstrap, Settings).
- **Usage Note "Flow 16, 20":** No flow-name legend exists in the CSV or docs (same gap noted in prior audits EP-038/EP-032), so these numbers cannot be mapped to named screens with certainty. The call-site footprint found (Seller Hub Home, Settings, Shop Details on mobile; seller dashboard, layout, Settings on web) is consistent with two flows ("view own seller profile/dashboard" and "edit seller settings"), but this is an inference, not a confirmed mapping.
- **Behavioral claim — Conflict:** "Verify a suspended seller's own profile view clearly reflects the suspended status" does not match the shipped system:
  - A suspended seller **cannot reach a 200 response from this endpoint at all** — `JwtStrategy.validate` (`jwt.strategy.ts:42`) rejects every authenticated request from a suspended account with `401 Account suspended.`, before `SellersController` runs. The same account-level check also blocks **login itself** (`auth.service.ts:166-168` and four more call sites) — so a suspended seller cannot even obtain a fresh session to try this call with.
  - Even hypothetically bypassing the auth gate, `SellersService.getProfile()`'s response DTO (`sellers.service.ts:500-523`) has no `suspended`/`status` field to "clearly reflect" anything — contrast with the admin-facing `getAllSellers`/`getSellerByIdForAdmin`, which do carry exactly such a field (Finding #3).
  - The team's own manual test documentation (`docs\manual-test-cases.md:548-551`) describes the **intended** behavior for suspension as a **login-time block** ("try to log in as the suspended user → Error: 'Your account has been suspended'"), not a profile-view state — which agrees with the code's actual behavior, but is the opposite framing from what this sheet row's title asks to verify.
  - A test written literally against this row's title (log in as a suspended seller, load their profile, assert a visible "Suspended" indicator) has no success path to execute against: the precondition ("a suspended seller's own profile view") is unreachable under the current account-lifecycle design.

---

## Test design inputs

**a. Roles and permissions**
- Anon/guest: 401, no token (`JwtAuthGuard` rejects with no user). Not role-gated beyond requiring auth.
- Logged-in non-seller `USER`: 403 `Insufficient permissions.` — `RolesGuard` live-checks `isSeller` (`roles.guard.ts:42-48`), ignores the stale JWT claim.
- Logged-in seller (`isSeller: true`, not suspended): 200, full profile DTO.
- Logged-in seller, **suspended** (`suspended: true`): **401 `Account suspended.`**, thrown at the `JwtAuthGuard`/`JwtStrategy` layer — never reaches `RolesGuard` or the controller. This applies identically whether the account is `isSeller: true` or `false`; suspension is account-wide, not seller-specific (`schema.prisma:277`, no separate `SellerStatus`).
- Admin (`Role.ADMIN`, not a seller): 403 — `@Roles('SELLER')` does not include `ADMIN`; an admin viewing seller data must use the separate `getSellerByIdForAdmin`/`getAllSellers` surface, not this endpoint.

**b. Ownership rules**
- Not applicable in the usual sense — there is no `:id` path param; `req.user.id` from the JWT is the only input, so "ownership" is definitionally the caller themselves. No cross-account access vector exists on this route (contrast with `GET /sellers/:userId/shop`, a separate, intentionally public endpoint).

**c. Resource states and visibility rules**
- Seller account states relevant here: `isSeller=false` (403), `isSeller=true, suspended=false, sellerProfile=null` (404 `Seller profile not found` — mid-onboarding edge case, distinct from suspension), `isSeller=true, suspended=false, sellerProfile set` (200, full DTO), `isSeller=true, suspended=true` (401, regardless of `sellerProfile` state — the suspension check runs before the profile is ever looked up).
- No `SellerStatus` enum / no "pending"/"banned"/"deactivated" states exist separately from the single `suspended` boolean — confirmed by `prisma\schema.prisma` grep (no match for `SellerStatus`, `enum.*Seller`, or `sellerStatus`).

**d. Validation and error paths**
- No request body/query/path params to validate — the only "input" is the bearer token.
- Observed outcomes: `200` (full profile), `401` (no token / invalid token / expired token / session revoked via `sid` check / **suspended account**), `403` (`isSeller` false), `404` (`sellerProfile` null). All four non-200 paths are real and distinct; the spec documents none of them.
- The `401` body shape for the suspended case specifically: Nest's default `UnauthorizedException('Account suspended.')` → `{statusCode: 401, message: 'Account suspended.', error: 'Unauthorized'}` (standard Nest exception filter shape, re-thrown verbatim by `jwt-auth.guard.ts:22`).

**e. Response contract**
- Fields actually returned: `shopName, shopTagline, shopLogo, phoneNumber, sellerCategories, addressLine1, city, state, zip, country, sellerType, legalName, taxIdLast4, notifyFollowersOnNewListing, payout, isSeller`. No `id`, no `suspended`, no `status`.
- OpenAPI declares **no schema** for the 200 response — every field above is an unvalidated contract gap vs. the spec.
- Nullability: `shopTagline`, `shopLogo`, `sellerType`, `legalName`, `taxIdLast4` nullable (explicit `?? null` in the mapper); `payout` nullable (whole object); everything else required per the code path (though `sellerProfile` itself gates existence via the 404).
- The sheet's specific ask — a field/flag/message making suspension visible in this response — **does not exist in the contract at all**, and per Finding #1 the response can never be reached for a suspended account regardless.

**f. Business logic / side effects**
- Read-only, no mutation, no counters, no notification side effects from this route itself.
- The side effect that matters for this row's scenario lives entirely in the **auth layer**, not this endpoint: suspending an account (`PATCH /admin/users/:id/suspend`) immediately invalidates every live session's next request (`jwt.strategy.ts:26-33` — explicitly documented as "load the LIVE user from the DB on every authenticated request... prevents stale JWT claims... from granting access after the underlying state has changed"). No notification/email/push to the seller was found wired to the suspend action itself (see Could Not Verify).

**g. Existing tests and docs**
- `sellers.service.spec.ts:720-828` — `getProfile` field mapping, payout masking (BRI-285/masking), BRI-285 null-handling, 404 on missing profile. **No suspended-seller case.**
- `jwt.strategy.spec.ts:92-105` — generic (all-endpoints) unit test that a suspended user's token is rejected with `UnauthorizedException`. Not endpoint-specific, but it is the test that actually backs Finding #1.
- `apiClient.refresh.test.ts:119-124` — mobile-side test that a `401 { message: 'Account suspended.' }` during the silent-refresh retry path triggers `expireSession()`. The clearest existing automated evidence of the real end-to-end behavior for this scenario.
- `docs\manual-test-cases.md:544-551` — manual test case for admin suspending a user, explicitly stating the **expected** mobile behavior is a login-time block with an error message, not a profile view with a status badge.
- No `sellers.controller.spec.ts`, no `*.e2e-spec.ts` for `GET /sellers/me`, found anywhere in `apps/api/test` or `apps/api/src/sellers`.

**h. Fixtures/accounts needed**
- A seller account with `isSeller: true`, `sellerProfile` populated, `suspended: false` (happy path).
- A seller account with `isSeller: true`, `sellerProfile: null`, `suspended: false` (404 case).
- A seller account with `isSeller: true`, `suspended: true` — created via `PATCH /admin/users/:id/suspend` (`admin.controller.ts:160-165`), requires an **admin** account/JWT to set up.
- A non-seller `USER` account (403 case).
- A valid JWT for each of the above, plus a **pre-suspension** JWT for the "already-authenticated session gets cut off mid-session" scenario (issue the token first, then suspend the account via the admin endpoint, then replay the token against `GET /sellers/me`).
- An admin JWT (to perform the suspend/unsuspend fixture setup — not to call this endpoint, which 403s for admins).

---

## Source agreement matrix

| Behaviour | Requirement/sheet | OpenAPI spec | Code (file:line) | Existing tests | Verdict |
|---|---|---|---|---|---|
| A suspended seller can successfully call `GET /sellers/me` and receive a profile payload | Sheet title implies yes (there must be a "profile view" to check) | Not documented (no 401 listed at all) | `jwt.strategy.ts:42` — throws 401 `Account suspended.` before the controller runs; `auth.service.ts:166-168` etc. also block login itself | `jwt.strategy.spec.ts:92-105` (generic), `apiClient.refresh.test.ts:119-124` (mobile-side, confirms end-to-end 401 handling) | **Conflict** — sheet's premise cannot occur under current code |
| The response body of `GET /sellers/me` contains a `suspended`/`status` field | Sheet title implies yes ("clearly reflects the suspended status") | No schema documented at all | `sellers.service.ts:500-523` — no such field; contrast `getAllSellers`/`getSellerByIdForAdmin` (`:1272-1273`, `:1311-1312`), which do have it | `sellers.service.spec.ts:720-828` — no test asserts a `suspended`/`status` key (because none exists) | **Conflict** — the field the title asks about does not exist on this endpoint's contract |
| Suspension is communicated to the seller at login time with an explicit error | Not addressed by sheet (sheet frames it as a profile-view concern) | Not documented | `auth.service.ts:166-168` (+4 more sites) — yes, `401 Account suspended.` at login | `docs\manual-test-cases.md:548-551` confirms this is the intended behavior | Agree (code + docs), but **Unspecified-in-requirement** relative to the sheet, which never mentions login at all |
| App surfaces the word "suspended" anywhere to the seller themselves | Sheet implies some surfaced message/flag | N/A | Mobile: generic "session expired" screen (`SessionExpired.tsx`), generic account-load error (`SellerSettings.tsx:170`); Web: silent `.catch(() => {})` (`layout.tsx:175`) or redirect-before-display (`sellerApi.ts:22-24`) | No test asserts the literal word "suspended" reaches any screen off this call path | **Conflict / Spec-gap** — even the login-time error (which the docs do call out) is not reliably traced through to user-visible text on this endpoint's call sites specifically |
| Auth requirement on this route | Not addressed by sheet | **Absent** (no `security`, no documented 401/403) | `JwtAuthGuard` + `RolesGuard`, `@Roles('SELLER')` | N/A | **Spec-gap** |
| Response schema for 200 | Not addressed by sheet | **Absent** | Full DTO at `sellers.service.ts:500-523` | Asserted field-by-field in unit tests | **Spec-gap** |
| 401/403/404 documented | Not addressed by sheet | **Absent** | All three thrown in distinct cases | Partially asserted (404 only, in unit tests) | **Spec-gap** |

---

## Suggested test scenarios

| # | Scenario | Role | Ownership | State/Input | Expected status | Response assertions | Expected source | Requirement status | Check level | Needs |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Fetch own profile as an active, fully-onboarded seller | Seller | Owner (self) | `isSeller:true`, `suspended:false`, `sellerProfile` set | 200 | Full DTO per contract; no `suspended`/`id` keys present | Code | Confirmed | Response-content | Seller fixture + JWT |
| 2 | Fetch own profile as a non-seller user | Buyer/`USER` | N/A | `isSeller:false` | 403 | `message: 'Insufficient permissions.'` | Code (`roles.guard.ts:55-61`) | Confirmed | Status-only | Buyer JWT |
| 3 | Fetch with no `Authorization` header | Guest | N/A | — | 401 | Standard Nest 401 body | Code (`jwt-auth.guard.ts`) | Confirmed | Status-only | None |
| 4 | **Fetch as a suspended seller (pre-existing valid JWT, account suspended mid-session)** | Seller | Owner (self) | `suspended:true`, token issued before suspension | 401 | `message: 'Account suspended.'` — NOT 200, no profile body at all | Code (`jwt.strategy.ts:42`) + test (`apiClient.refresh.test.ts:119-124`) + doc (`manual-test-cases.md:548-551`) | **Conflict with sheet title** — sheet assumes a 200 with a visible status; code gives 401 with no body | Status-only + Business-rule | Owner JWT minted before suspension + admin fixture to flip `suspended` after |
| 5 | **Attempt login as a suspended seller (precondition for the sheet's scenario)** | Seller | Owner (self) | `suspended:true`, fresh login attempt (password/OTP/social) | 401 | `message: 'Account suspended.'` | Code (`auth.service.ts:166-168` + 4 more sites) + doc | Confirmed | Status-only | Suspended seller fixture |
| 6 | Non-owner attempting to read someone else's "me" data via this endpoint | Any authenticated seller | N/A (no `:id` param exists) | — | N/A — route has no target-user input, so cross-account access is structurally impossible here | Confirms no IDOR surface on this specific route | Code (no path param) | Confirmed | Security | None — documents the absence of this risk class, not a defect |
| 7 | Sheet-title-literal scenario: "suspended seller's own profile view clearly reflects the suspended status" | Seller | Owner (self) | `suspended:true` | **Per sheet: 200 with a visible suspended indicator. Per code: 401, no body, no indicator exists.** | Flag as a scenario with no trustworthy expected result until the title/code conflict is resolved by PO/QA — cannot be automated as literally written | Sheet (conflict) | **Conflict** | Business-rule | Needs product/QA clarification: is the intended behavior "block before profile" (current) or "allow profile view with a suspended banner" (sheet's literal ask)? |
| 8 | Confirm `getAllSellers`/`getSellerByIdForAdmin` DO show `suspended`/`status` for the same seller (cross-endpoint contrast, context only) | Admin | N/A | Suspended seller fixture | 200 | `status: 'suspended'`, `suspended: true` present | Code (`sellers.service.ts:1272-1273`, `:1311-1312`) | Confirmed | Response-content | Admin JWT + suspended seller fixture — out of strict EP-109 scope, but needed to prove the field exists elsewhere |
| 9 | Unexpected query params sent to `GET /sellers/me` | Seller | Owner | `?foo=bar` | 200, ignored | Response unaffected | QA suggestion | Assumed | Negative | Seller JWT |
| 10 | Malformed/expired/tampered JWT | Any | N/A | invalid signature / expired token | 401 | Standard 401 body, no 500/leak | Code (`jwt.strategy.ts`, pinned `HS256` algorithm) | Confirmed | Security | Expired/invalid token fixture |
| 11 | Session revoked via "sign out all devices" (`sid` check) then retry `GET /sellers/me` with the old token | Seller | Owner | revoked session, `suspended:false` | 401 | `message: 'Session ended. Please sign in again.'` — a **different** 401 reason than suspension, important to distinguish in any negative-test suite for this endpoint | Code (`jwt.strategy.ts:44-52`) | Confirmed | Business-rule | Owner JWT + a way to revoke its `sid` |
| 12 | Response does not include `id` on any role that can reach 200 | Seller | Owner | active, onboarded | 200 | `id` key absent from body (contract gap vs. mobile's required `SellerProfile.id` type) | Code vs. mobile type (Finding #4) | Confirmed (code-evidenced) | Contract | Seller JWT — static/contract check, not business-rule |

---

## Summary

- 0 unused request params/items (zero request items declared at all; the only "input" is the bearer token, and it is consumed by the guard chain).
- 2 response-contract gaps: `suspended`/`status` never present in this DTO despite being modeled on the same service for admin views (Finding #3), and `id` declared required on the mobile client type but never actually sent by the backend (Finding #4).
- 1 dead-data finding: `user.suspended` is already loaded into memory inside `getProfile()` via the unselected Prisma query but is never mapped into the response (Finding #2).
- 1 central, high-confidence conflict: the sheet's premise — that a suspended seller can view their own profile and see the suspended status reflected in it — is structurally impossible under the shipped auth design (`JwtStrategy` + `AuthService` both reject suspended accounts with a 401 before any profile data is ever assembled or returned). This is corroborated by the team's own `docs/manual-test-cases.md`, which frames suspension as a login-time block, not a profile-view state.
- 2 UX findings (not bugs, but relevant to test design): both mobile and web discard the specific "Account suspended." message on this call's error path, surfacing only generic "session expired"/"couldn't load" copy.
- 1 test-coverage gap: no controller spec exists for `SellersController` at all, and no existing test exercises `GET /sellers/me` against a suspended fixture specifically.
- 3 spec-gaps consistent with the rest of the audited API: no response schema for 200, no 401/403/404 documented, no security scheme declared.
- 12 suggested test scenarios (see table above), with scenario #7 flagged as the one that cannot be given a trustworthy expected result until the sheet's title is clarified against the shipped account-suspension design.

**Primary finding:** the endpoint itself is correctly built and genuinely used in both apps, but the sheet row's specific test intent is unexecutable as written: suspension is enforced one layer up (authentication), not inside this endpoint's response, so there is no world in which a suspended seller reaches a `200` from `GET /sellers/me` to inspect for a "suspended" indicator — and even the admin-facing sibling DTOs that do carry such a field make clear this was a deliberate design choice elsewhere in the same service, not an oversight. Flagged to QA/PO to decide whether the row should be rewritten around the actual (login-blocking) behavior, or whether product wants a genuinely new capability (let a suspended seller log in and see a "Suspended" banner on their own dashboard) — not resolved here per instructions.
