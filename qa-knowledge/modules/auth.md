# Module: auth

22 endpoints. Controller: `apps/api/src/auth/auth.controller.ts`. Service: `apps/api/src/auth/auth.service.ts` (1439 lines). Repository: `apps/api/src/auth/auth.repository.ts` (Prisma access for `EmailOtp`, `OtpLockout`, `RefreshToken` only — user CRUD is delegated to `UsersService`/`UsersRepository`, which `AuthModule` imports via `UsersModule`). Guards: `apps/api/src/auth/guards/jwt-auth.guard.ts` (applied), `optional-jwt-auth.guard.ts` (exists, **not used anywhere in this controller** — grep shows no auth/users route references it). Strategy: `apps/api/src/auth/strategies/jwt.strategy.ts`. Module wiring: `apps/api/src/auth/auth.module.ts`.

Cross-cutting facts that apply to every endpoint below unless noted:
- **No class-level guard** on `AuthController` — each protected route carries its own `@UseGuards(JwtAuthGuard)` (`auth.controller.ts:159,184,192,201,210,222` for `/refresh-claims`, `/sessions`, `/sessions/revoke-others`, `/sessions/:id` DELETE, `/change-password`, `/verify-current-password`). Verified by reading the controller directly, not inferred from naming.
- **`@Throttle(STRICT)` = 10 req/min/IP** (`auth.controller.ts:29`) on every route except `/refresh-claims` (no throttle decorator — it requires a valid JWT already, so brute force is less of a concern) and `/logout` (no throttle decorator either). This is tighter than the global 100/min default.
- **Global `ValidationPipe`** (`whitelist: true, forbidNonWhitelisted: true, transform: true`) rejects any body/query field not declared on the DTO, with a custom `exceptionFactory` returning `{ message, error: 'Bad Request', field }`.
- **`AllExceptionsFilter`** reshapes every uncaught exception to `{ success: false, statusCode, message, error? }` and never leaks internals.
- **JWT**: HS256 pinned (`jwt.strategy.ts:22`), `Authorization: Bearer <token>`, secret from `JWT_SECRET` via `ConfigService`. `JwtStrategy.validate()` re-loads the **live** user from the DB on every request (`findRawById`) — stale claims (role/isSeller/suspended) cannot grant access after the underlying row changes. A token carrying `sid` (BRI-454) is additionally checked against `AuthService.isSessionLive(sid)` — revoked-session tokens die immediately, not just at their next refresh.
- **Two session models coexist**: (a) BRI-334 rolling sessions — short-lived (`JWT_ACCESS_EXPIRES_IN`, default `45m`) access token + 90-day rotating refresh token (`${id}.${secret}` opaque string), used by every real mobile sign-in path; (b) legacy single long-lived token (`JWT_EXPIRES_IN`, default `7d`) used only for `role === 'ADMIN'` sessions and the web seller-portal passwordless OTP login (`verifySellerOtpLogin` calls `signToken` directly with `legacyTokenExpiry()`, bypassing `issueSession`). A legacy token has no `sid` and is immune to the sessions/revoke endpoints below.
- **bcrypt** rounds from `BCRYPT_ROUNDS` (default 12 for auth.service, default 10 for account-deletion — see users.md).

---

## GET /auth/check-availability
`apps/api/src/auth/auth.controller.ts:40` → `AuthService.checkAvailability` (`auth.service.ts:1166`)

- **Auth**: none (public). Throttled (STRICT).
- **Query params** (`CheckAvailabilityDto`): `field` (required, `@IsIn(['email','username'])`), `value` (required, `@IsString() @MinLength(1)`).
- **Business rule**: `value` is trimmed and lowercased before lookup (`normalised = value.trim().toLowerCase()`), then `UsersRepository.findByEmail`/`findByUsername` (exact match, not partial). Returns `{ available: boolean }` — `true` when no row matches.
- **DB**: one read (`User.findUnique` by `email` or `username`).
- **Errors**: 400 if `field` isn't `email`/`username` or `value` is empty. No 404/409 — availability is always a 200.
- **No pagination/external deps.**
- Used as the real-time pre-check behind signup's email-continue flow (see Frontend below) — it is the *only* enforcement point for "is this username free" that happens before a full signup attempt; the actual create path (`assertUsernameAvailable`) re-checks regardless, so this is UX-only, not the security boundary.

## POST /auth/signup
`auth.controller.ts:47` → `AuthService.signup` (`auth.service.ts:128`)

- **Auth**: none (public, provisions a new account). Throttled.
- **Headers**: `X-Device-Name` / `X-Device-Platform` (optional, free text, cleaned/capped to 100 chars by `deviceFromHeaders()` in `session-device.ts`) — used only to label the Security-page session row, never for access control.
- **Body** (`SignupDto`): `name` (string, required), `username` (string, required — no format constraint on this DTO itself, unlike `UpdateProfileDto`'s `^[a-z0-9_]{3,30}$`), `email` (`@IsEmail`), `password` (`@MinLength(8)` + `@Matches(/(?=.*[A-Z])(?=.*\d)/)` — one uppercase, one digit).
- **Business rules**:
  - `BR-AUTH-001`: email must not already belong to a user → 409 `ConflictException('You have already signed up. Please sign in.')` (`auth.service.ts:129-131`).
  - `BR-AUTH-002`: username must be available → `UsersService.assertUsernameAvailable` throws 409 `UsersService.USERNAME_TAKEN` ("That username is already taken.") if taken. No disambiguation/suffix — a requested username is honored exactly or refused (BRI-305 applies to this path too, though BRI-305's own fix narrative is about the OTP path).
  - Password is bcrypt-hashed (`BCRYPT_ROUNDS`, default 12) before storage.
  - A new session is issued via `issueSession(user, device, { firstSignIn: true })` — `firstSignIn: true` suppresses the BRI-348 new-device alert (the very first sign-in is the account owner setting up, not an intrusion).
- **DB writes**: `User.create` (via `UsersRepository.create` — also creates a stub `SellerProfile` row *only* if `isSeller` is passed, which this path never does) + `RefreshToken.create` (new rotation family).
- **Success response**: `{ success: true, token, refreshToken, user: { id, email, username, name, role, isSeller, sellerStatus } }`. `sellerStatus` computed by `sellerStatusOf()` (`'none'|'pending'|'active'`, never `'active'` for a fresh signup).
- **Errors**: 409 (email taken), 409 (username taken), 400 (DTO validation).
- **No pagination.** External dep: none (no email sent on this path — contrast with the OTP path, which emails a welcome/sign-in code).
- **FRONTEND**: no production caller found in `apps/mobile` or `apps/web` — only `apps/mobile/src/services/__tests__/authApi.test.ts` exercises `authApi.signup()`. The real mobile signup flow is entirely OTP-based (`POST /auth/otp/verify`, see below). Classify as **implemented and tested server-side, dead in both production frontends today** — see `identity.gaps.md`.

## POST /auth/login
`auth.controller.ts:54` → `AuthService.login` (`auth.service.ts:160`)

- **Auth**: none (public). Throttled. `@HttpCode(200)` (not 201).
- **Headers**: same `X-Device-*` as signup.
- **Body** (`LoginDto`): `email` (`@IsEmail`), `password` (`@IsString`, no format check on login — only on create/reset).
- **Business rules**:
  - `BR-AUTH-003`: credential check is `bcrypt.compare` against `user.password`; a missing user and a wrong password are **both** reported as the same 401 `'Invalid credentials.'` (`auth.service.ts:162-164`) — no email-enumeration via error text.
  - `BR-AUTH-004`: `user.suspended === true` → 401 `'Account suspended.'`, checked *after* the credential check (so a suspended account doesn't leak "this is a valid account" ahead of a correct password — though the message itself does distinguish once authenticated, which is accepted as already past the risky unauthenticated boundary).
  - `BR-AUTH-005`: a successful login **cancels a pending account deletion** if one is scheduled (BRI-375) — `cancelPendingDeletionOnLogin()` runs after the suspension check, before issuing the session. Failure here is swallowed (logged) and returns `accountRestored: null` rather than failing the login — see `users.md` BR-USERS block for the deletion-service side.
- **DB**: 1 read (`findByEmail`) + up to 1 write (`cancelDeletion`, conditional) + `RefreshToken.create` (new session).
- **Success response**: `{ success: true, accountRestored: {requestedAt, scheduledFor} | null, token, refreshToken, user: {...} }`.
- **Errors**: 401 (bad credentials), 401 (suspended), 400 (DTO).
- **FRONTEND**: `apps/mobile/src/services/authApi.ts:258` exports `authApi.login()`; grep across `apps/mobile/src/screens` finds **no caller** — only `authApi.test.ts` calls it. On web, `apps/web/src/lib/sellerApi.ts:319` and `apps/web/src/lib/api.ts:90` both define a password-based `.login()`, but neither is called from any web page — the web admin flow goes through `app/api/admin/login/route.ts` (a Next.js server route that calls `/auth/login` server-to-server, never through the browser-facing `adminApi.login()`/`sellerApi.login()` wrappers), and the web seller flow is OTP-only via `UnifiedLogin.tsx`. **`POST /auth/login` is invoked in production exclusively by the Next.js admin-login route handler** — every direct client-side caller of it is dead code. See `identity.gaps.md`.

## POST /auth/forgot-password
`auth.controller.ts:62` → `AuthService.forgotPassword` (`auth.service.ts:191`)

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`ForgotPasswordDto`): `email` (`@IsEmail`).
- **Business rule `BR-AUTH-006`**: always returns `{ success: true, message: 'If that email exists, a reset code has been sent.' }` regardless of whether the email exists — anti-enumeration. A 6-digit numeric OTP (`randomInt(100000,1000000)`) is generated and stored as **plaintext** on `User.resetToken` (not hashed — contrast with the passwordless-OTP and account-deletion codes, both of which store only a bcrypt hash) with `resetTokenExpiry = now + RESET_TOKEN_TTL_MINUTES` (config, default 20 min).
- **DB**: 1 read + 1 write (`setResetToken`) if the user exists; 1 read only if not.
- **External dep**: `MailService.sendOtpEmail` — failure is caught, logged, and does **not** surface to the client (`try { await this.mail.sendOtpEmail(...) } catch (err) { this.logger.error(...) }` — the outer function still returns success).
- **Errors**: 400 (DTO) only — there is no 404/409 path by design.
- **FRONTEND**: `authApi.forgotPassword()` exists (`authApi.ts:261`) with no production caller (test-only). No password-reset screen/flow found in mobile or web in this scope.

## POST /auth/verify-otp
`auth.controller.ts:70` → `AuthService.verifyOtp` (`auth.service.ts:216`) — **the legacy password-reset OTP verify**, distinct from the passwordless sign-in OTP (`/auth/otp/verify`) below. Do not conflate the two flows — they use different storage (`User.resetToken` plaintext vs. `EmailOtp.codeHash` bcrypt) and different endpoints.

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`VerifyOtpDto`): `email` (`@IsEmail`), `otp` (`@Length(6,6)`).
- **Business rules**: plaintext compare `user.resetToken !== dto.otp` → 400 `'Invalid code.'`; separately checks `resetTokenExpiry < now` → 400 `'Code has expired.'`. No attempt lockout, no resend-cooldown — unlike the passwordless OTP flow, this one has none of the BRI-443/BRI-7 hardening.
- **Success**: `{ success: true, token: dto.otp }` — echoes the OTP back as a "token" for the client to carry into `/auth/reset-password`'s `token` field (the same 6-digit string becomes the reset token).
- **FRONTEND**: `authApi.verifyOtp()` exists, test-only caller.

## POST /auth/reset-password
`auth.controller.ts:78` → `AuthService.resetPassword` (`auth.service.ts:999`)

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`ResetPasswordDto`): `token` (string, the OTP from the step above), `newPassword` (same `@MinLength(8)` + uppercase/digit `@Matches` as signup).
- **Business rules**: looks up user by `resetToken` (`findFirst`, not `findUnique` — `resetToken` is not declared `@unique` in the schema), 400 if not found or if `resetTokenExpiry < now`. On success, `updatePassword()` writes the new bcrypt hash **and clears `resetToken`/`resetTokenExpiry`** in the same write (`users.repository.ts:144-149`) — single-use token.
- **Does NOT revoke existing refresh-token sessions** — a password reset leaves every other signed-in device's session alive (no call to `revokeRefreshTokenFamily`/similar). Cross-reference `identity.gaps.md`.
- **FRONTEND**: `authApi.resetPassword()` exists, test-only caller; no screen found.

## POST /auth/otp/request
`auth.controller.ts:86` → `AuthService.requestOtpLogin` (`auth.service.ts:431`) — the real, production passwordless **buyer** sign-in request step.

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`RequestOtpDto`): `email` (`@IsEmail`), `name` (optional, `@MaxLength(60)` — only used to greet a brand-new signup's welcome email; ignored for an existing account).
- **Business rules** (`BR-AUTH-007..011`):
  - Email normalized (`trim().toLowerCase()`).
  - **BRI-443 email-scoped lockout checked FIRST**: if `OtpLockout` has an active `lockedUntil`, throws 429 with `{ code: 'OTP_LOCKED', retryAfterMs, message }` *before* issuing a new code — closes the hole where a fresh code reset the 5-attempt counter.
  - **Resend allowance**: max 3 resends per code "cycle" (`OTP_MAX_RESENDS = 3`), tracked via `EmailOtp.resendCount`; the 4th request inside the same still-live window starts a 15-minute cooldown (`OTP_COOLDOWN_MS`) and throws 429 `{ code: 'OTP_COOLDOWN' }`. "Continuing" the cycle requires the previous code to still be unexpired and not already cooling down — otherwise the count resets to 0 (new cycle).
  - Code is a 6-digit `randomInt`, bcrypt-hashed (`BCRYPT_ROUNDS`) for storage; **plaintext cached in-memory only when `NODE_ENV !== 'production'`** (`devOtpCodes` Map, read by `GET /auth/dev/otp`).
  - `EmailOtp` row upserted with `expiresAt = now + OTP_TTL_MS` (**60,000 ms = 1 minute**, per BRI-332's 13-Oct-2026 product decision — history: 30s → 10min (BRI-448) → 1min (BRI-332)) *before* the email send attempt; then `startOtpWindow()` **restamps** `expiresAt` to `now + OTP_TTL_MS` again right after the email leaves, so the 1-minute window is measured from delivery, not from mint time (BRI-217 fix — a slow SMTP relay used to eat most of the window before the user ever saw the code).
  - Name resolution for the email body: existing user's stored name wins; otherwise `dto.name` (trimmed) or a name derived from the email's local-part (`nameFromEmail`).
  - **Always returns `{ success: true }`** — a cooldown/lockout DOES surface as a thrown 429 here (unlike the seller-scoped twin below, which swallows these into a uniform 200 to avoid confirming seller status).
- **DB writes**: `EmailOtp` upsert (×2 effectively — initial + restamp), `OtpLockout` read only (no write unless locked-out branch fires, which throws before any write).
- **External dep**: `MailService.sendSigninOtpEmail` (async; failure is caught/logged, does not fail the request — the 200 has already implicitly been promised by this point in the flow, though note the restamp only happens in the `try` block after a successful send).
- **FRONTEND (mobile)**: `apps/mobile/src/services/authApi.ts:330` `authApi.requestOtp()`, called from the email-entry step of sign-up/sign-in (`useEmailContinue.ts` drives `checkAvailability`, and the OTP screens — `EmailEntry`/`OtpEntry` per test files — drive `requestOtp`/`verifyOtpLogin`). Error mapping: `toOtpError()` classifies by the API's `code` field first (`OTP_LOCKED`→'locked', `OTP_COOLDOWN`→'rate-limited' on the request phase), falling back to message-sniffing for older API builds.
- **FRONTEND (web)**: `sellerApi.requestOtp()` is the **buyer-flavored** endpoint but is reused by the web Seller Portal's `UnifiedLogin.tsx` — wait, no: web's seller login actually calls `/auth/otp/seller/request` (see below), not this one. Confirmed by reading `sellerApi.ts:330` — `requestOtp()` posts to `/auth/otp/seller/request`. So this buyer endpoint (`/auth/otp/request`) has **no web caller**, mobile-only.
- **Copy mismatch found**: `apps/web/src/components/UnifiedLogin.tsx:131` hardcodes *"It expires in 10 minutes"* for the seller OTP email — the actual TTL (shared constant, `OTP_TTL_MS`) is 1 minute. Mobile's own copy (`OtpEntry.tsx`, per its test "waits a full minute before Resend unlocks") is consistent with the real 1-minute TTL. This is a **stale web copy bug**, not a code-path difference — see `identity.gaps.md`.

## POST /auth/otp/verify
`auth.controller.ts:94` → `AuthService.verifyOtpLogin` (`auth.service.ts:468`) — the real buyer sign-in/sign-up completion. This is the **primary account-creation endpoint actually used by the mobile app** (not `POST /auth/signup`).

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Headers**: `X-Device-*`.
- **Body** (`VerifyOtpLoginDto`): `email` (`@IsEmail`), `code` (`@Length(6,6)`), and a large optional onboarding-draft block used **only** when the email has no existing account: `name` (≤60), `username` (optional, `^[a-z0-9_]{3,30}$`, lower-cased, blank→undefined transform), `prefsSkipped` (bool), `categories`/`brands`/`styles` (string arrays), `sizes` (`{tops,bottoms,boots}` nested object), `zip` (`^\d{5}$`), `ageBracket` (one of `AGE_BRACKETS` — note the EN DASH separator, a hyphen is rejected), `gender` (one of `GENDERS`). Every optional field uses a blank-string→`undefined` `@Transform` specifically to avoid BRI-136 (an unanswered optional step mustn't 400 as "invalid").
- **Business rules** (`BR-AUTH-012..019`):
  - `loadVerifiableOtp()` shared preamble: lockout check first (`OTP_LOCKED`), then record-exists check (`OTP_NOT_FOUND`), then cooldown check (`OTP_COOLDOWN`), then expiry check (`OTP_EXPIRED` — also deletes the row), then attempts-exhausted check (`OTP_LOCKED` again, since `attempts >= 5` without a fresh lockout row yet would otherwise read as "not found"). Order matters and is itself a business rule (tested implicitly by which error code a given state produces).
  - Code compared via `bcrypt.compare`; a wrong code calls `registerFailedOtpAttempt()` → increments `EmailOtp.attempts`; on the 5th failure the row is deleted (code *invalidated*, not merely blocked — a later lucky resubmission of the same code cannot succeed) and `lockEmail()` starts/escalates an `OtpLockout` (`OTP_LOCKOUT_BASE_MS=15min`, doubling each repeated lockout up to `OTP_LOCKOUT_MAX_MS=24h`).
  - Correct code: `forgetOtp()` (delete row) + `clearLockout()` (a genuine success resets the escalating lockout counter to zero).
  - **If no user exists for the email** → account is created on the spot (`isNewUser: true`): username is either the caller's explicit request (re-validated via `assertUsernameAvailable`, 409 if taken — BRI-305, honored exactly, never silently suffixed) or derived (`uniqueUsername(email)` — tries the email local-part, then up to 5 numeric-suffixed candidates, then a timestamp suffix as a last resort). A P2002 unique-constraint race on `username` (two concurrent signups for the same free handle) is caught and remapped to the same 409 `USERNAME_TAKEN` rather than a raw 500. A random unusable password hash is set (passwordless account). `zip`/`ageBracket`/`gender` are persisted **only on create** — a returning user's profile is never overwritten by a stale device-local draft.
  - **If user exists and is suspended** → 401 `'Account suspended.'` (onboarding-draft fields are silently ignored in this branch).
  - **If user exists and is not suspended** → `cancelPendingDeletionOnLogin()` runs (same BRI-375 rule as `/auth/login`).
- **DB**: 1 read (OTP) + ≥1 write (attempts increment OR delete+lockout OR delete+clear-lockout) + conditional `User.create` (new) or `User` deletion-cancel write (existing) + `RefreshToken.create`.
- **Success response**: `{ success: true, isNewUser, accountRestored, token, refreshToken, user: {...plus interests, prefsSkipped, categories, sizes, brands, styles} }` — richer than `/auth/login`'s user object (includes the onboarding facets, since this is also the signup path).
- **Errors**: 400 (`OTP_NOT_FOUND`/`OTP_EXPIRED`/`OTP_INVALID`/DTO), 429 (`OTP_LOCKED`/`OTP_COOLDOWN`), 401 (suspended), 409 (username taken, including the race case).
- **FRONTEND**: `authApi.verifyOtpLogin()` (`authApi.ts:346`), the real production entry point — screens per `apps/mobile/src/screens/auth/__tests__/OtpEntry.test.tsx`/`EmailEntry.test.tsx` drive it, passing the onboarding draft (`SetupProfile.tsx`, `AgeGender.tsx` per `signup-profile.constants.ts`'s own doc comment) only for a fresh signup. `toOtpError()` maps every documented error code/status to a typed `OtpError` for the UI to branch on.

## POST /auth/social/google
`auth.controller.ts:102` → `AuthService.loginWithGoogle` (`auth.service.ts:583`)

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`GoogleLoginDto`): `firebaseIdToken` (`@IsString @IsNotEmpty @MaxLength(4096)`) — a Firebase ID token minted client-side after the native Google sheet; verified server-side via `firebase-admin`'s `verifyIdToken(token, true)` (the `true` = check revocation against Firebase, a network call).
- **Business rules (`BR-AUTH-020..023`)**:
  - Token must decode and must have `firebase.sign_in_provider === 'google.com'` (blocks a password/anonymous Firebase token being swapped in) → 401 otherwise.
  - Lookup by `googleId` first; if no match, lookup by `email` — if that email already belongs to a **different** (non-Google-linked) account → 409 `'An account already exists for this email. Sign in with email instead.'` (no silent account linking).
  - A brand-new Google account requires `identity.emailVerified === true` from Firebase's own claim — an unverified email is refused (401) rather than trusted.
  - Existing + suspended → 401. Existing + not suspended → `cancelPendingDeletionOnLogin()`.
- **DB**: lookups by `googleId`/`email`, conditional `User.create` (`signInMethod: 'GOOGLE'`, unusable random password), `RefreshToken.create`.
- **External dep**: Firebase Admin SDK (`verifyIdToken` — network call to Google; failure → 401 `'Invalid sign-in token.'`).
- **Success/response shape**: same rich shape as `/auth/otp/verify`'s success response (includes onboarding facets, all null/default for a Google-created account since there's no onboarding-draft body here).
- **FRONTEND**: `authApi.loginWithGoogle()` (`authApi.ts:378`), real caller per `apps/mobile/src/auth/social/socialLogin.ts` (referenced from `authStore.logout()`'s `clearSocialSessions()`) and the Landing/GuestGatePopup sign-in rows.
- **Known Linear tickets**: REDB1-73 (Apple button shown on Android — UI gating, not this endpoint), BRI-648 ("Google Sign-In is not linked to existing Email-OTP account" — Backlog — consistent with the code's deliberate no-silent-link rule above; this is a **product-scoped limitation, not a bug**, per the code comment "only Google itself vouches for the email here... so a Google token whose email already belongs to a different account is refused rather than silently linked").

## POST /auth/social/apple
`auth.controller.ts:110` → `AuthService.loginWithApple` (`auth.service.ts:687`)

- Same shape as Google, keyed on `appleId` instead of `googleId`, provider check `'apple.com'`.
- **Apple-specific rule (`BR-AUTH-024`)**: Apple only shares an email on the first sign-in with the app, and the user can decline it — a *returning* user's token may carry no email at all, which is fine (lookup is by `appleId`). A **new** account with no/unverified email is refused (401) rather than backfilled with a placeholder (would collide with `User.email`'s uniqueness).
- Response for an existing user omits `accountRestored` entirely in the success payload shape coded here (`auth.service.ts:722-743` — the returned object literal has no `accountRestored` key on this branch, unlike Google/OTP) — **inconsistency flagged**: the method computes nothing for `accountRestored` on the existing-user branch for Apple (no call to `cancelPendingDeletionOnLogin` at all for Apple/Facebook non-suspended existing users — see below).
- **Gap found**: unlike `/auth/login`, `/auth/otp/verify` and `/auth/social/google`, **`loginWithApple` and `loginWithFacebook` never call `cancelPendingDeletionOnLogin()`** for an existing, non-suspended user (`auth.service.ts:716-718` and `:805-807` — the `else` branch after the suspended check is empty; contrast Google's `else { accountRestored = await this.cancelPendingDeletionOnLogin(user); }`). A user who deleted their account and then signs back in via Apple or Facebook **does not get the deletion auto-cancelled** — BRI-375's "signing in during the window restores the account" is only honored for email/password, email-OTP, and Google sign-in. See `identity.gaps.md` — this reads as a real, unticketed correctness gap, not an inferred one (cite: `auth.service.ts:693-718` vs `:583-621`).
- **FRONTEND**: `authApi.loginWithApple()`; REDB1-73 (Apple shown on Android where it can't complete, status QA Passed) and BRI-310 (same bug, Done — the Android-specific suppression) are the relevant tickets; these are UI-gating bugs, independent of the deletion-restore gap above.

## POST /auth/social/facebook
`auth.controller.ts:118` → `AuthService.loginWithFacebook` (`auth.service.ts:776`)

- Same shape again, keyed on `facebookId`, provider check `'facebook.com'`. Same missing-`cancelPendingDeletionOnLogin()` gap as Apple (see above).
- **FRONTEND**: `authApi.loginWithFacebook()`. Tickets: REDB1-12 ("Continue with Facebook opens a blank page" — Canceled), REDB1-123 ("Error occurs when logging in with Facebook" — copied from BRI-829, status Todo/open as of this analysis) — an **open, unresolved bug** against this flow as of 2026-11-10.

## POST /auth/otp/seller/request
`auth.controller.ts:128` → `AuthService.requestSellerOtpLogin` (`auth.service.ts:872`) — web Seller Portal passwordless sign-in. **Never provisions a new account** (contrast the buyer twin).

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`RequestOtpDto`, same as buyer — `name` field is accepted but has no effect here since no account is ever created).
- **Business rules (`BR-AUTH-025..027`)**: a code is emailed **only if** `user?.isSeller && !user.suspended`; otherwise nothing is sent. **Every branch returns `{ success: true }` unconditionally** — including the lockout and cooldown cases, which are *swallowed* here (just logged as a warning) specifically so the response can never be used to fingerprint which emails are seller accounts (contrast the buyer version, which does throw 429 for lockout/cooldown — that asymmetry is deliberate per the code comment, not an oversight).
- **DB/external dep**: identical `EmailOtp`/mail mechanics as the buyer request, scoped by the `isSeller` gate.
- **FRONTEND**: `sellerApi.requestOtp()` (`apps/web/src/lib/sellerApi.ts:330`), called from `UnifiedLogin.tsx:129,156` (initial request + resend). No mobile caller (seller phone-OTP for mobile seller *onboarding* is a different endpoint entirely, under the `sellers` module — cross-reference only, out of this batch's scope per the task brief).

## POST /auth/otp/seller/verify
`auth.controller.ts:136` → `AuthService.verifySellerOtpLogin` (`auth.service.ts:915`)

- **Auth**: none. Throttled. `@HttpCode(200)`.
- **Body** (`VerifyOtpLoginDto` — same DTO as the buyer verify, so it technically *accepts* the onboarding-draft fields, but they are never read/used in this method).
- **Business rules (`BR-AUTH-028..030`)**: same `loadVerifiableOtp`/attempt-lockout mechanics as the buyer flow. On a correct code, **no account is created** — `if (!user || !user.isSeller) throw new UnauthorizedException("This email isn't a registered seller account.")`. Suspended sellers are also refused. `cancelPendingDeletionOnLogin()` **is** called here for a valid seller.
- **Session model**: uses the **legacy long-lived token** (`signToken(..., this.legacyTokenExpiry())`) directly, bypassing `issueSession()`/BRI-334 rotation entirely — this session has no `sid`, doesn't appear on `GET /auth/sessions`, and can't be revoked via `/auth/sessions/:id` or `/auth/sessions/revoke-others`. Documented deliberately in the code comment ("Web-only... kept on the legacy long-lived single token").
- **Success**: `{ success: true, accountRestored, token, user: {...no refreshToken key at all} }`.
- **FRONTEND**: `sellerApi.verifyOtp()`, called from `UnifiedLogin.tsx:135` — checks `res.user.isSeller` client-side too (belt-and-braces; the API already guarantees it) and rejects with a client-only message if somehow false.

## GET /auth/dev/otp
`auth.controller.ts:147` → `AuthService.getDevOtp` (`auth.service.ts:1376`)

- **Auth**: none, but **404s unconditionally when `NODE_ENV === 'production'`** (`this.config.get('NODE_ENV') === 'production' → throw NotFoundException()`), checked in the controller before even calling the service. Throttled.
- **Query** (`DevGetOtpDto`): `email` (`@IsEmail`).
- **Business rule**: reads the in-memory `devOtpCodes` Map (never persisted, never populated at all in production per `issueOtpCode`'s own gate) — 404 if no pending code for that email.
- **Purpose**: QA/test automation convenience so a script can complete the OTP flow without reading a real inbox — explicitly a non-prod-only backdoor, not a security boundary (the data it returns is already dev-only).
- **FRONTEND**: no caller in either app (used by external test tooling / Postman per the code's own comment "QA automation convenience").

## POST /auth/refresh-claims
`auth.controller.ts:157` → `AuthService.refreshClaims` (`auth.service.ts:1024`)

- **Auth**: `JwtAuthGuard` **applied** (verified in controller source). Not throttled (requires an already-valid token).
- **Business rule**: re-mints an access token carrying the caller's **current** DB claims (role/isSeller/name) off an already-valid token, **preserving the caller's `sid`** so the new token still maps to the same session-row on `GET /auth/sessions` (`signToken(..., sid)`). This is NOT the BRI-334 refresh-token exchange — no new refresh token is issued, and the old access token keeps working until it naturally expires (this just lets the client get a fresher one proactively, e.g. right after a seller confirmation lands mid-session).
- **Only documented caller**: mobile's `sellSubmit.ts` 403 handler (per the code comment) — refreshes claims when a stale `isSeller: false` claim causes a 403 on a seller-only action mid-session.
- **Errors**: 401 if the user id from the JWT no longer resolves to a row (`findRawById` returns null).
- **FRONTEND**: `authApi.refreshClaims()` (`authApi.ts:287`).

## POST /auth/refresh
`auth.controller.ts:165` → `AuthService.refreshSession` (`auth.service.ts:1047`)

- **Auth**: none (public — the entire point is this must work even after the access token has expired). Throttled.
- **Body** (`RefreshTokenDto`): `refreshToken` (`@MinLength(1)`) — opaque `${id}.${secret}` string, **not a JWT**.
- **Business rules (`BR-AUTH-031..035`, BRI-334)**:
  - Token is split on the first `.`; malformed (no `.`, empty id, or empty secret) → 401 `'Session expired. Please sign in again.'`.
  - Row looked up by `id` (point lookup, not a scan).
  - **Reuse detection**: if the found row is already `revokedAt !== null`, the **entire rotation family** is revoked (`revokeRefreshTokenFamily`) and 401 is thrown — this is the explicit security response to a replayed/stolen token, not a normal-expiry path. Logged as a warning.
  - Expired row (`expiresAt < now`) → 401, no family revocation (this is ordinary expiry, not reuse).
  - `bcrypt.compare(secret, row.secretHash)` must match → 401 otherwise.
  - On success: **rotation** — a new row is created and the old one is marked `revokedAt`/`replacedById` **in one `$transaction`** (15s timeout, 5s maxWait — deliberately generous since this sits on the hot silent-refresh path) so a crash mid-rotation can never leave a token both "current" and "replaced". New access token carries the **same `familyId`** as `sid`. Device name/platform are carried forward from the old row (not re-read from headers — a silent background refresh has no fresh device headers to offer).
  - New refresh-token expiry is **always `now + JWT_REFRESH_EXPIRES_IN_DAYS` (default 90)** — a rolling window, not counted from original issuance (BRI-334's explicit "Remember Me" requirement: any activity, including a silent refresh, extends the session another full 90 days).
- **DB**: 1 read (`findRefreshTokenById`) + `$transaction` of 2 writes (create + update) on success, or an `updateMany` (family revoke) on reuse detection.
- **Success**: `{ token, refreshToken }` — no `user` object (contrast every sign-in endpoint).
- **FRONTEND**: `authApi.refreshSession()`, the **only** caller is `apiClient`'s own 401-interceptor logic (per the code comment and `apps/mobile/CLAUDE.md`'s "401 handling" section) — never called directly by a screen.

## POST /auth/logout
`auth.controller.ts:173` → `AuthService.logoutSession` (`auth.service.ts:1095`)

- **Auth**: none required at the HTTP layer (deliberately — logout must work even against an already-expired access token; it only needs the *refresh* token). Not throttled. `@HttpCode(200)`.
- **Body** (`RefreshTokenDto`): `refreshToken`.
- **Business rule**: best-effort, idempotent — a malformed token, or one with no matching row, is silently a no-op (not an error). A valid token revokes its **whole rotation family** (not just the presented row), so any already-rotated-forward token in the same chain also dies.
- **Response**: `{ success: true }` always (controller wraps the void service call).
- **FRONTEND**: `authApi.logout()` (`authApi.ts:302`), called from `authStore.logout()` **after** reading the outgoing refresh token but is fire-and-forget from the UI's perspective — local sign-out proceeds regardless of whether the server call lands. Called alongside (but ordered after) `notificationsApi.unregisterPushToken()` — push-token unregistration deliberately happens first because it still needs the (still-live) access token, and the refresh-revoke kills the session.

## GET /auth/sessions
`auth.controller.ts:183` → `AuthService.listSessions` (`auth.service.ts:1112`) — BRI-454.

- **Auth**: `JwtAuthGuard` applied.
- **Business rule**: one row per **live rotation family** (`revokedAt IS NULL AND expiresAt > now`) belonging to the caller — a legacy/admin token (no `sid`, no `RefreshToken` row at all) simply has nothing to list here even though the caller IS authenticated via such a token (the controller doesn't special-case this; it just queries by `userId` and gets zero or more rows). `signedInAt` = the oldest row in the chain (first login); `lastActiveAt` = the current head's `createdAt` (≈ time of last silent refresh, roughly every 45 min while in use). The caller's own session (`req.user.sid`) is marked `current: true` and sorted **first**; the rest keep most-recently-active order.
- **DB**: 2 reads (`findLiveSessionHeads` + a `groupBy` for `findSessionStartTimes`).
- **Response**: `SignedInSession[]` — `{ id, deviceName, platform, signedInAt, lastActiveAt, current }[]`.
- **FRONTEND**: `authApi.getSessions()`, rendered by `screens/profile/Security.tsx` (loads on mount, "Devices" section).

## POST /auth/sessions/revoke-others
`auth.controller.ts:190` → `AuthService.revokeOtherSessions` (`auth.service.ts:1136`) — BRI-454.

- **Auth**: `JwtAuthGuard`. Throttled. `@HttpCode(200)`.
- **Business rule**: **requires `req.user.sid`** — a token minted before BRI-454 (no `sid`) can't say which session is "this one", and revoking everything would also sign the caller out, so the call is refused with 400 `'Please sign in again to manage your devices.'` rather than guessing. Otherwise revokes every other live family for the user.
- **DB write**: `updateMany` on `RefreshToken` (`revokedAt: null, familyId: not current → revokedAt: now`).
- **Response**: `{ revoked: number }`. Side effect: those other devices' **access tokens** stop working on their very next request (via `JwtStrategy`'s live `isSessionLive(sid)` check) — not merely at their next silent-refresh attempt.
- **FRONTEND**: `authApi.revokeOtherSessions()`, `Security.tsx`'s "Sign out all other devices" — guarded client-side by a `useRef` latch (`revoking.current`) against double-tap, and a friendly "No other devices signed in" short-circuit when the only row left is `current`.

## DELETE /auth/sessions/:id
`auth.controller.ts:199` → `AuthService.revokeSession` (`auth.service.ts:1151`) — BRI-348.

- **Auth**: `JwtAuthGuard`. Throttled. `@HttpCode(200)`.
- **Params**: `:id` = a `familyId` (not a `RefreshToken` row id).
- **Business rule**: scoped to the **caller's own** sessions — `revokeSession(userId, familyId)`'s `updateMany` filters on `userId` too, so someone else's family id is indistinguishable from an unknown one: **both produce 404** `'That device is no longer signed in.'` (never a 403 that would confirm the id belongs to someone). Revoking the **current** session (`familyId === currentSid`) is explicitly allowed — the response's `current: boolean` tells the caller to treat it like a normal logout and clear local state.
- **Response**: `{ success: true, current: boolean }`.
- **FRONTEND**: `authApi.revokeSession()`. `Security.tsx`'s `signOutDevice()` branches client-side: tapping "Sign out" on the **current** row shows a confirm dialog and calls the local `logout()` store action (which itself calls `/auth/logout`, a different endpoint) **instead of** hitting this endpoint — so in practice, this DELETE endpoint's `current: true` response path is reachable from the API but the mobile UI's own current-device sign-out never actually calls it (it pre-empts with a client-side branch). This endpoint IS called for every **other** (non-current) row.

## POST /auth/change-password
`auth.controller.ts:208` → `AuthService.changePassword` (`auth.service.ts:1186`)

- **Auth**: `JwtAuthGuard`. Throttled. `@HttpCode(200)`.
- **Body** (`ChangePasswordDto`): `currentPassword` (string), `newPassword` (same `@MinLength(8)` + uppercase/digit rule).
- **Business rules**: `bcrypt.compare(currentPassword, user.password)` must match → 401 `'Current password is incorrect.'` otherwise. On success, `updatePassword()` also clears `resetToken`/`resetTokenExpiry` as a side effect (shared repo method with the forgot-password flow) — stray reset tokens die on any password change. A confirmation email (`MailService.sendPasswordChanged`) is sent best-effort (failure logged, not surfaced).
- **Does NOT revoke other devices' refresh-token sessions** — same gap noted under `/auth/reset-password`. A stolen password that gets changed by the legitimate owner does not force other signed-in devices to re-authenticate. See `identity.gaps.md`.
- **FRONTEND**: `authApi.changePassword()`, `ChangePasswordScreen.tsx` — on success calls the **local** `logout()` (which separately calls `/auth/logout` to revoke the *current* session's own refresh-token family) so the user must sign in again with the new password on this device; other devices are unaffected both server-side and by any client action.

## POST /auth/verify-current-password
`auth.controller.ts:220` → `AuthService.verifyCurrentPassword` (`auth.service.ts:1179`)

- **Auth**: `JwtAuthGuard`. Throttled (explicitly — "can't be used as a brute-force oracle" per the code comment, since it's an unlimited-guess password oracle if not rate-limited).
- **Body** (`VerifyPasswordDto`): `password`.
- **Business rule**: returns `{ valid: boolean }` rather than throwing — this is a UX pre-check (the Change Password screen's on-blur validation), never used as the actual authorization gate for anything.
- **FRONTEND**: `authApi.verifyCurrentPassword()`, `ChangePasswordScreen.tsx`'s `handleCurrentBlur()` — fires on blur of the "Current password" field, sets inline error state; failures here are swallowed to `null` (not surfaced) so a transient network/rate-limit error doesn't falsely claim the password is wrong.

---

## Guard-application audit (explicit per task instruction — don't trust naming)

| Route | Decorator present? | Verified at |
|---|---|---|
| `check-availability`, `signup`, `login`, `forgot-password`, `verify-otp`, `reset-password`, `otp/request`, `otp/verify`, `social/google`, `social/apple`, `social/facebook`, `otp/seller/request`, `otp/seller/verify`, `dev/otp`, `refresh`, `logout` | **No guard** (public by design) | `auth.controller.ts` — no `@UseGuards` on these methods |
| `refresh-claims`, `sessions` (GET), `sessions/revoke-others`, `sessions/:id` (DELETE), `change-password`, `verify-current-password` | `@UseGuards(JwtAuthGuard)` | lines 159, 184, 192, 201, 210, 222 |
| *(none)* | `RolesGuard`/`@Roles` | Not used anywhere in this controller — no admin- or seller-only route exists in `auth` |
| *(none)* | `OptionalJwtAuthGuard` | Exists in `apps/api/src/auth/guards/` but is not referenced by any route in `auth.controller.ts` or `users.controller.ts` — it is used elsewhere in the codebase (other modules), out of this batch's scope |
