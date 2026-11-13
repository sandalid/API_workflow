# Module: users

21 endpoints. Controller: `apps/api/src/users/users.controller.ts`. Services: `UsersService` (`users.service.ts`, profile/social-graph), `AccountDeletionService` (`account-deletion.service.ts`, self-service deletion). Repositories: `UsersRepository` (`users.repository.ts`), `AccountDeletionRepository` (`account-deletion.repository.ts`, own tables/queries — "almost nothing here is a user read" per its own doc comment). Module: `users.module.ts` (HTTP-serving slice) + `users-worker.module.ts` (BullMQ purge processor, no controller, never loaded by the API process). `account-purge.processor.ts` runs hourly in the worker, not reachable via any endpoint.

Cross-cutting facts:
- **No class-level guard** — `UsersController` is explicitly "mixed public/private", documented in its own comment (`// No class-level guard — GET /:id is public. Auth applied per-route below.`). Verified per-route below.
- **Route-ordering is load-bearing**: `me`, `me/preferences`, `me/push-token`, `me/active`, `me/deletion*`, and `sellers` are all declared **before** `:id` so NestJS's path matching resolves the literal-prefix routes first — if `:id` were declared first, a request for `/users/me` would match `:id = 'me'` instead. The controller's own comments call this out twice.
- **`SafeUser` never includes `password`/`resetToken`/`deleteCodeHash`/`sellerConfirmToken`** — `UsersService.toSafeUser()` is the one allow-list mapping from Prisma's raw `User` to the wire shape; every `/users/me`-family response goes through it.
- **`sellerStatus` derivation** (`'none'|'pending'|'active'`) is written **twice identically** — `UsersService.toSafeUser` (`users.service.ts:617-621`) and `AuthService.sellerStatusOf` (`auth.service.ts:1216-1221`) — both compute `isSeller ? 'active' : sellerConfirmToken ? 'pending' : 'none'`. Mobile's `utils/sellerState.ts` mirrors this a third time and additionally defines a **client-only `'verifying'` status** the server never sends (set locally by `SellerSettingUp` while Stripe onboarding is still running) — per `apps/mobile/CLAUDE.md`, omitting `'verifying'` from a local copy of this predicate sends a seller who just finished signup back through onboarding. Not applicable to any `users`-module endpoint directly, but every endpoint that returns `sellerStatus` (`GET/PATCH /users/me`, `PATCH /users/me/preferences`) feeds that mirror.

---

## GET /users/me
`users.controller.ts:26` → `UsersService.findById` (`users.service.ts:179`)

- **Auth**: `JwtAuthGuard` applied.
- **Business rule**: straight lookup by `req.user.id` → `toSafeUser()`. Returns `null` if the user row is somehow gone (can't realistically happen given `JwtStrategy` already 401's on a missing user, but the service signature allows it) — **note**: a `null` return here is not converted to a 404 by the controller; it would serialize as a literal `null` body with 200 status. Treat as a latent (very low probability, since `JwtStrategy.validate()` already guarantees the row exists moments earlier) edge case.
- **DB**: 1 read.
- **Response (`SafeUser`)**: `id, name, username, email, avatar, coverImage, bio, location, country, zip, ageBracket, dateOfBirth (YYYY-MM-DD string), gender, interests, phone, isSeller, sellerStatus, prefsSkipped, personalizedRecommendations, notificationPrefs (7 booleans, defaulted via resolveNotificationPrefs), categories, sizes, brands, styles, followerCount, followingCount, salesCount, rating, createdAt, updatedAt`.
- **FRONTEND**: `usersApi.getMe()` — the **primary identity-bootstrap call**, used by `authStore.hydrate()` on cold start (after reading a persisted token from SecureStore) to rebuild `authUser` and decide `activeRole`. Also `sellerApi.getMe()` on web (`SellerUser` subset: `id,email,name,username,bio,avatar,role,isSeller`) — called from `seller/settings/page.tsx` and `seller/reviews/page.tsx`.

## PATCH /users/me
`users.controller.ts:33` → `UsersService.updateProfile` (`users.service.ts:264`)

- **Auth**: `JwtAuthGuard`.
- **Body** (`UpdateProfileDto`): `name` (required, trimmed, `@IsNotEmpty` — BRI-314 "no minimum length" product decision, blank-after-trim fails `@IsNotEmpty` not a length check, message mirrored word-for-word by mobile's `utils/nameRules.ts`), `username` (**optional** — BRI-281 removed the mobile buyer's username field; omitting it leaves the stored handle untouched; when sent, `^[a-z0-9_]{3,30}$`), `bio` (≤160), `location`/`country` (≤80 each), `interests` (one of `INTERESTS_OPTIONS` = `["Men's wear","Women's wear","Men's and Women's wear"]`), `avatar`/`coverImage` (string URL, no format validation beyond `@IsString`), `phone` (≤30, **the buyer's own contact number** — distinct from `SellerProfile.phoneNumber`, which this endpoint never touches), `ageBracket` (one of `AGE_BRACKETS`, EN-DASH-separated), `gender` (one of `GENDERS`), `dateOfBirth` (ISO date, `@IsPlausibleDateOfBirth()` custom validator — BRI-327, captured **alongside** `ageBracket`, not replacing it; drives a future age-gate, not enforced as one yet — cross-ref REDB1-146 below).
- **Business rules (`BR-USERS-001..004`)**:
  - Username-conflict check only runs **if `username !== undefined`** — `findUsernameConflict(username, excludeUserId)` (a `findFirst` excluding the caller's own row) → 409 `USERNAME_TAKEN` if another user already holds it.
  - `phone` uses `dto.phone.trim() || null` — an **empty string explicitly clears** the stored phone (distinct from omitting the field, which leaves it alone). Every other optional field (`bio`,`location`,`country`,`interests`) uses `?? null` instead — sending `null`/omitting `avatar`/`coverImage` leaves them `undefined` (unchanged), per the spread-conditional pattern (`...(dto.phone !== undefined ? {...} : {})`).
  - `ageBracket`/`gender`/`dateOfBirth` are **only written when the field is present in the body** (same conditional-spread pattern) — a profile save that doesn't touch these never silently wipes a value captured at signup.
- **DB**: 1 conditional read (username-conflict check) + 1 write (`User.update`).
- **Response**: full `SafeUser` (same shape as GET).
- **FRONTEND**: `usersApi.updateProfile()` — `screens/profile/PersonalInfo.tsx` (name/phone; `zip`/`ageBracket`/`dateOfBirth`/`gender` are rendered **read-only** there per the screen's own comment, "whether they should be editable here is an open question on BRI-327" — so the DTO supports editing these fields but the current signed-off mobile screen never sends them). Web: `sellerApi.updateUserProfile({name,username,bio})` from `seller/settings/page.tsx`.
- **Linear**: REDB1-146 ("Enforce under-18 block on financial agreements using dateOfBirth", Todo/open) confirms `dateOfBirth` is capture-only today, no enforcement — matches the DTO comment exactly.

## PATCH /users/me/preferences
`users.controller.ts:44` → `UsersService.updatePreferences` (`users.service.ts:334`)

- **Auth**: `JwtAuthGuard`.
- **Body** (`UpdatePreferencesDto`): `categories`/`brands`/`styles` (string arrays — `brands` holds **names**, e.g. `"Ariat"`, resolved to Brand ids case-insensitively downstream by the feed, per the DTO's own doc comment), `sizes` (`{tops,bottoms,boots}`), `personalizedRecommendations` (bool), `notifications` (`NotificationPrefsDto` — all 7 keys optional, **partial update**: a key absent from the body keeps its previously-saved value).
- **Business rules (`BR-USERS-005..009`, BRI-521/BRI-342)**:
  - **Only a real shopping-facet** (`categories`/`sizes`/`brands`/`styles` — checked via `Object.keys(facets).length > 0`) clears `prefsSkipped` to `false`. Saving `personalizedRecommendations` or `notifications` alone does **not** clear it — the Home cold-state onboarding nudge is tied specifically to "did the user ever set a shopping facet", not to "did they touch Settings at all".
  - **Notification-prefs merge** (BRI-521): when `dto.notifications` is present, the current saved prefs are read (`resolveNotificationPrefs(current.notificationPrefs)` — defaults-filled), then only the keys actually present and boolean in the incoming body overwrite the corresponding key — every omitted key is preserved. This is the server-side half of the fix for "toggles revert after leaving the screen".
  - **Mailchimp sync side effect** (BRI-342): if `notifications.marketing` is sent and **differs from the previously-saved value**, a fire-and-forget `mailchimp.subscribe(email)`/`unsubscribe(email)` call fires *after* the DB write returns — a no-op re-save of the same value never re-triggers a Mailchimp API call. Failure is caught and logged, never surfaces to the client (the user's own preference row has already saved regardless of Mailchimp's reachability).
- **DB**: 1 conditional read (only when `notifications` is in the body, to compute the merge/diff) + 1 write.
- **Response**: full `SafeUser`.
- **FRONTEND**: `usersApi.updatePreferences()`. Per `apps/mobile/CLAUDE.md`: `NotificationSettings.tsx` saves each toggle individually (`{ notifications: { [key]: value } }`) behind a per-key `useRef` latch to avoid a double-tap race; `ShoppingPreferences.tsx`/onboarding screens save the facet arrays.
- **Linear status conflict worth flagging**: BRI-521 ("toggles do not persist") shows status **Reopened** in Linear even though the merge logic described above is fully present in `users.service.ts` and documented as fixed in `apps/mobile/CLAUDE.md`. Either (a) the ticket was reopened for a residual client-side race not covered by the per-key latch, or (b) the Linear status is stale relative to the code. **Evidence classification: conflicting** — code says fixed, ticket says reopened. Flag for runtime verification; do not assume either source alone. Same pattern for BRI-443 (OTP lockout) — see `auth.md`.

## POST /users/me/push-token
`users.controller.ts:55` → `UsersService.updatePushToken` (`users.service.ts:321`)

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Body** (`RegisterPushTokenDto`): `expoPushToken` (string, ≤200).
- **Business rule (`BR-USERS-010`, BRI-423)**: registering a token against `userId` **also detaches that same token from every other account currently holding it** (`updatePushToken`'s repo method runs `updateMany({ expoPushToken, id: {not: id} } → null)` then the real update, inside one `$transaction`). A token identifies a *device*, not an account — without this, signing out of account A and into account B on the same phone would leave both rows holding the same token, so a push meant for A could land on B's session.
- **DB**: `$transaction` of 2 writes.
- **Response**: `{ success: true }`.
- **FRONTEND**: `notificationsApi.registerPushToken()` (note: the mobile service wrapper for this endpoint lives in `services/notificationsApi.ts`, not `usersApi.ts`, despite the route being under `/users/`) — called from `services/pushNotifications.ts`'s registration flow after obtaining an Expo push token and the user grants permission.

## DELETE /users/me/push-token
`users.controller.ts:70` → `UsersService.clearPushToken` (`users.service.ts:328`)

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Business rule**: idempotent no-op if the user has no token stored. Must be called **before** the refresh token is revoked client-side (needs a still-valid access token) — documented in the controller's own comment and mirrored in `authStore.logout()`'s explicit ordering (`unregisterPushToken` before `authApi.logout`).
- **Response**: `{ success: true }`.
- **FRONTEND**: `notificationsApi.unregisterPushToken()` — called from **both** `authStore.logout()` and `authStore.expireSession()` (BRI-390 added the `expireSession()` call specifically, since a softer session-expiry used to skip this and leave the outgoing account's push token live on the device).

## POST /users/me/active
`users.controller.ts:85` → `UsersService.markActive` (`users.service.ts:315`) — BRI-335.

- **Auth**: `JwtAuthGuard`. `@HttpCode(204)` (No Content — the only `users`/`auth` endpoint in this batch that returns 204 rather than 200/201).
- **Business rule**: stamps `User.lastActiveAt = now()`. Deliberately **not** a side effect of every authenticated request (would make a backgrounded/polling app read as "active") — called only on app foreground/resume.
- **DB write**: `update` with `select: { id: true }` only (no need to ship the row back for a 204).
- **Consumers of `lastActiveAt`**: `GET /users/:id` (public profile's "Last active N ago"), `GET /auth/sessions` is unrelated (uses `RefreshToken.createdAt`, not this field).
- **FRONTEND**: `usersApi.markActive()` — called on app foreground per the endpoint's doc comment; exact call site not traced further in this batch (out of scope: would require tracing app-lifecycle hooks, not a `users`/`auth` service file).

## GET /users/me/deletion
`users.controller.ts:103` → `AccountDeletionService.getEligibility` (`account-deletion.service.ts:134`) — BRI-288/BRI-375, step 1 of 3.

- **Auth**: `JwtAuthGuard`.
- **Business rule (`BR-USERS-011`)**: read-only, safe to poll. Computes **live** blocker counts, not cached: `activeOrders` (order status in `BLOCKING_ORDER_STATUSES = ['placed','processing','packed','shipped','out_for_delivery']`, counted on **both** `buyerId` and `sellerId` — a seller mid-ship is blocked from deleting just as much as a buyer awaiting a parcel), `pendingPayouts` (+ `pendingPayoutCents` sum, status in `['pending','held_unverified','reversal_failed']`), `openDisputes` (status in `['seller_evidence_window','awaiting_decision','approved','refund_failed']` — note `approved` still blocks because the refund hasn't issued yet, and `refund_failed` blocks harder). `windowDays` is 30 normally, **60 if there's been order/payout/dispute activity in the last 30 days** (`ACCOUNT_DELETION_ACTIVITY_LOOKBACK_DAYS`, config-overridable). `canDelete = all three blocker counts are 0`.
- **DB**: 1 read (`findById`) + 1 aggregate-heavy read (`countBlockers`, 3 parallel queries) + 1 read (`hasRecentFinancialActivity`, 3 parallel `findFirst`s).
- **Response (`DeletionEligibilityDto`)**: `{ canDelete, blockers: {activeOrders, pendingPayouts, pendingPayoutCents, openDisputes}, windowDays, scheduledFor, requestedAt }` — the latter two non-null only if a deletion is already scheduled (lets the warning screen detect "you already have one in flight", though the current mobile `DeleteAccountScreen` doesn't appear to branch on that specifically — it just uses `canDelete`/`blockers`/`windowDays`).
- **Errors**: 404 if the user row is gone or already `deletedAt` (can't happen for the caller's own still-valid session in practice).
- **FRONTEND**: `usersApi.getDeletionEligibility()`, loaded on mount by `DeleteAccountScreen`'s step-1 "warn" screen; renders the live blocker sentence (`blockerSentence()`) replacing a previously-hardcoded one (BRI-288's whole point).

## POST /users/me/deletion/request
`users.controller.ts:113` → `AccountDeletionService.requestDeletion` (`account-deletion.service.ts:180`) — step 2 of 3.

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Business rules (`BR-USERS-012..014`)**:
  - 409 `'This account is already scheduled for deletion.'` if `deletionScheduledFor` is already set — no double-scheduling.
  - **Blockers are re-checked here** (not trusted from the eligibility read) → 409 with a human-readable `"Resolve these before deleting your account: N active orders, $X in pending payouts, N open disputes."` if any block.
  - A 6-digit code is generated, bcrypt-hashed (`BCRYPT_ROUNDS`, default **10** here — note: different default than `auth.service.ts`'s default of 12; both ultimately read the same `BCRYPT_ROUNDS` env var in practice, so they agree at runtime, but the hardcoded fallback constants differ if the env var is ever unset), stored on `User.deleteCodeHash`/`deleteCodeExpiry` (`now + DELETE_CODE_TTL_MS` = 20 minutes).
  - The confirmation email send is **awaited, not fire-and-forget** (explicit deliberate choice per the code comment — "the only honest outcome is an error they can retry, not a success they cannot act on" — contrasts with every OTP-email send elsewhere in `auth`, which is fire-and-forget-with-logging). A mail-send failure therefore surfaces as a thrown error to the client here, unlike the sign-in OTP paths.
- **DB**: 1 read + 1 read (blockers) + 1 write (`setDeleteCode`).
- **External dep**: `MailService.sendAccountDeletionCode` (awaited — failure propagates).
- **Response**: `{ success: true, emailSentTo: maskEmail(email) }` — masked as `j***@example.com` so even a logged response body never carries the full address.
- **FRONTEND**: `usersApi.requestDeletionCode()`, `DeleteAccountScreen.handleRequestCode()` (step 2→3 transition) — on failure, re-fetches eligibility (`loadEligibility()`) since a blocker could have appeared between opening the screen and submitting.

## POST /users/me/deletion/confirm
`users.controller.ts:125` → `AccountDeletionService.confirmDeletion` (`account-deletion.service.ts:217`) — step 3 of 3, **the only call in this flow that changes anything durable**.

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Body** (`ConfirmAccountDeletionDto`): `code` (`^\d{6}$` exactly — not `@Length(6)`, since the screen already strips non-digits; anything else is treated as a malformed client, not a user typo, and rejected at the DTO boundary before reaching bcrypt), `reason` (optional, ≤200, "product feedback, not a record").
- **Business rules (`BR-USERS-015..018`)**:
  - 400 if no `deleteCodeHash`/`deleteCodeExpiry` set (`'Request a new code to continue.'`), 400 if expired, 400 `"That code isn't right."` if the bcrypt compare fails. **No attempt-lockout** on this code (contrast the sign-in OTP's 5-attempt lockout) — an unlimited number of wrong guesses may be submitted, rate-limited only by the global throttler (not `STRICT` — this controller has no `@Throttle` decorators at all; the `users` module relies solely on the global 100/min/IP default).
  - **Blockers checked a third time**, immediately before the write — the code comment explicitly notes steps 1 and 2 can both be minutes old.
  - `windowDays` recomputed fresh (not reused from an earlier read) and `scheduledFor = now + windowDays`.
  - Code is burned in the **same write** that schedules the deletion (`scheduleDeletion()` nulls `deleteCodeHash`/`deleteCodeExpiry` alongside setting `deletionRequestedAt`/`deletionScheduledFor`/`deletionReason`) — a second confirm attempt with the same code can never replay.
- **DB**: 1 read + 1 read (blockers) + 1 read (recent-activity lookback) + 1 write.
- **Response**: `{ success: true, scheduledFor (ISO), windowDays }`.
- **FRONTEND**: `usersApi.confirmDeletion()`, `DeleteAccountScreen.handleConfirm()` — on success shows the real purge date (replacing a prior hardcoded "within 30 days", BRI-288's headline fix) and offers "Back to start" which calls the local `logout()`.
- **Account is NOT destroyed by this call** — only the window opens. The actual purge is a separate, out-of-band worker process (see below).

## GET /users/me/deletion/dev-code
`users.controller.ts:140` → `AccountDeletionService.getDevDeleteCode` (`account-deletion.service.ts:116`)

- **Auth**: `JwtAuthGuard`, **plus** a controller-level production gate identical to `GET /auth/dev/otp` (404 if `NODE_ENV === 'production'`).
- **Business rule**: reads the in-memory `devDeleteCodes` Map (never populated in production, per the same double-gate pattern as the sign-in OTP). Scoped to the **caller's own** id via the guard — can never hand back another user's pending code.
- **FRONTEND**: no caller found in mobile/web — QA automation convenience only, mirroring `GET /auth/dev/otp`.

## DELETE /users/me/deletion
`users.controller.ts:154` → `AccountDeletionService.cancelDeletion` (`account-deletion.service.ts:266`)

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Business rule (`BR-USERS-019`)**: cancels a pending deletion if one exists — guarded in the repository on `deletionScheduledFor: {not: null}, deletedAt: null`, so it's a safe no-op (`wasScheduled: false`) against an account with nothing scheduled, and structurally cannot "resurrect" an already-purged account (`deletedAt` guard) even though that row's window columns would already be null anyway.
- **Response**: `{ success: true, wasScheduled: boolean }`.
- **This is the endpoint an explicit "change your mind" UI action would call** — but **no mobile frontend reference was found** for it in the analyzed scope. The documented, actually-used cancel path is the **automatic** one inside `AuthService.cancelPendingDeletionOnLogin()`, called from every sign-in method except Apple/Facebook (see `auth.md` gap). `DeleteAccountScreen.tsx` itself has no "cancel" step/button — once a user reaches step 4 ("done"), the only action is `logout()`. **Classify as "no frontend reference found in the analyzed scope"** per task instruction (not "unused" — it may be intended purely as the server-side backstop + a hypothetical future "I changed my mind" button, or reachable from a screen outside this batch's scope, e.g. an in-flight Settings banner during the pending window that this batch didn't trace).

## GET /users/sellers
`users.controller.ts:167` → `UsersService.browseSellers` (`users.service.ts:473`) — BRI-328.

- **Auth**: `JwtAuthGuard` applied (note: this is a **discovery** endpoint but still requires sign-in — a guest cannot browse sellers to follow via this route; cross-reference `useAuthGate`'s 'follow'/'join' gates on mobile).
- **Query** (`BrowseSellersQueryDto` extends `GetUserSubresourceQueryDto`): `page` (default 1, min 1), `limit` (default 20, min 1, max 50), `q` (optional, ≤100, trimmed-to-undefined-if-blank, strips a leading `@` — BRI-405: the UI prompts "Search by @handle" but `username` is stored without the `@`, so a literal `contains: '@sale'` would never match the stored `sale`).
- **Business rules (`BR-USERS-020..022`)**: `isSeller: true, suspended: false`, excludes the caller (`NOT: {id: viewerId}`), optional `q` matches `name` **OR** `username` case-insensitively (partial). Sorted `followersCount: desc` — most-followed first, so a buyer with zero follows sees active shops rather than an arbitrary/empty-looking list.
- **Response fields per row**: `id, username, displayName, avatar, salesCount` (live `_count.sellerOrders` filtered to `COMPLETED_SALES = {status:'delivered'}`, not the stale denormalized column), `rating` (raw stored average, **not** zeroed/normalized — the client must check `reviewCount` alongside it to distinguish "0.0 average" from "unrated"), `reviewCount`, `listingCount` (filtered to `LIVE_LISTING_WHERE` i.e. `approved`/`active` only — a shop with 1 live item and 9 sold ones reads as "1 product", not 10).
- **Pagination**: page/offset, `{ data, page, limit, total }`.
- **FRONTEND**: `usersApi.browseSellers()`, `screens/profile/BrowseSellers.tsx` (per BRI-629's reference) — the Following list's empty-state "Browse sellers" CTA destination (BRI-328). Tickets: BRI-647 ("no option to browse more sellers from Following" — Done), BRI-512 ("following a seller from Browse sellers navigates away from the list" — Done), BRI-629 (2.0 search-bar restyle — open/QA Testing).

## GET /users/:id
`users.controller.ts:178` → `UsersService.getPublicProfile` (`users.service.ts:385`)

- **Auth**: **none** — public, confirmed (no `@UseGuards` on this method, and it's declared after the `me`/`sellers` literal routes so those match first).
- **Business rule**: any `id` resolves, including a **suspended** account's (the DTO includes `isSuspended: boolean` so the client can decide what to render — the endpoint itself does not 403/404 a suspended user, unlike the follow endpoint below which treats suspended-as-not-found). 404 if no such user id exists at all.
- **Response (`PublicProfile`)**: `id, username, displayName, avatar, coverImage, bio, location, role, isSuspended, followersCount, followingCount (both floored at 0), salesCount (COMPLETED_SALES only), rating (sellerRating() — 0 only when genuinely unrated, see ratingCount), ratingCount, listingsCount, createdAt, lastActiveAt, avgShipDays` (BRI-336: mean whole days from `createdAt`→`shippedAt` over orders shipped in the last 90 days, rounded half-up via `Math.round`, `null` if nothing shipped in that window — the service explicitly hides the stat rather than showing "0 days").
- **DB**: 1 read (`findPublicProfile`, with `_count` subselects) + 1 read (`findRecentShipTimes`, a 90-day-windowed `Order.findMany`).
- **FRONTEND**: `usersApi.getPublicProfile()`, `ShopProfile.tsx`'s seller-header render.

## GET /users/:id/listings
`users.controller.ts:184` → `UsersService.getUserListings` (`users.service.ts:432`)

- **Auth**: none (public).
- **Query** (`GetUserSubresourceQueryDto`): `page` (default 1), `limit` (default 20, max 50).
- **Business rule**: 404 via `assertUserExists()` if the id doesn't exist at all (does **not** check suspended — a suspended seller's listings endpoint still 200s, though `LIVE_LISTING_WHERE` naturally filters to approved/active listings regardless of seller status). Filtered to `LIVE_LISTING_WHERE` (approved/active, not-deleted) only — drafts/pending/rejected/sold/inactive never surface here.
- **Response shape**: same `ListingListItem` shape as `GET /listings` (seller block, brand, category, images[0], like/comment counts, `status` flattened to `'sold'|'available'` **plus** a separate `listingStatus` carrying the real lifecycle value).
- **FRONTEND**: **no frontend reference found in the analyzed scope.** `ShopProfile.tsx` (the obvious consumer) instead calls `listingsApi.getListingsBySeller(sellerId, page, limit, status?)` → `GET /listings?sellerId=...` (confirmed: `apps/mobile/src/services/listingsApi.ts:400-401`), a **different endpoint in the `listings` module**, not this one. This dedicated `users/:id/listings` route appears unused by either frontend in the analyzed scope — classify as a genuine duplicate-surface gap (two endpoints answer "this seller's listings", only one is wired), see `identity.gaps.md`.

## GET /users/:id/likes
`users.controller.ts:195` → `UsersService.getUserLikes` (`users.service.ts:438`) — BRI-522.

- **Auth**: `JwtAuthGuard` **applied** — confirmed in source (`@UseGuards(JwtAuthGuard)` at line 196), fixing the historical bug (BRI-522, "guest can view another user's liked listings without a token") where this route previously had no guard at all.
- **Ownership rule (`BR-USERS-023`)**: `requesterId !== userId` → 403 `"You can only view your own liked listings"` — enforced in the **service**, not the guard (the guard only proves "signed in as someone", the service proves "signed in as THIS someone"). A token-less request now gets 401 (guard); a valid token for a different user gets 403 (service); both reads are blocked, closing the ticket's two halves.
- **Business rule**: results additionally filtered at the repository level to skip listings that are soft-deleted (`NOT_DELETED`) or in `NON_LIKEABLE_LISTING_STATUSES` — a like placed before a status change, or against a listing later pulled, never resurfaces a dead row's full details in the wishlist.
- **Query**: `page`/`limit` (same bounds as above).
- **Response**: `{ data: ListingListItem[], page, limit, total }`.
- **FRONTEND**: `usersApi.getUserLikes()` — called **only with the caller's own id** per its own doc comment and the service's enforcement (Wishlist screen, `likesStore` hydrate per `apps/mobile/CLAUDE.md`'s BRI-522 note: "the app only ever reads its own list").

## GET /users/:id/followers
`users.controller.ts:206` → `UsersService.getUserFollowers` (`users.service.ts:448`)

- **Auth**: none (public).
- **Business rule**: 404 via `assertUserExists`. Only **`status: 'accepted'`** edges ever surface (there is no pending-approval state in practice for this app's follow model — see `BR-USERS-024` below — but the query still filters defensively). No pagination — returns the **full** list in one response (`{ data: [...] }`, no `page`/`limit`/`total`), ordered `createdAt: desc`.
- **Response row**: `id, username, displayName, avatar, salesCount (COMPLETED_SALES), followedAt`.
- **FRONTEND**: `usersApi.getMyFollowers()` (name is generic in the mobile wrapper despite hitting the generic `:id` route) — not traced to a specific screen in this batch beyond the wrapper's existence; web: `sellerApi.getFollowers()` hits a **different** endpoint (`/sellers/me/followers`, seller-module, out of this batch's scope) for the seller portal's own followers page — this `users/:id/followers` route itself has no confirmed web caller.

## GET /users/:id/following
`users.controller.ts:212` → `UsersService.getUserFollowing` (`users.service.ts:495`)

- Same shape as followers, reversed direction (`followerId: userId`), row carries the **followee's** info.
- **FRONTEND**: `usersApi.getMyFollowing()`, `screens/profile/FollowingList.tsx` (per its own test file) — rendered against the caller's own id, driving the empty-state → Browse Sellers (BRI-328) hand-off.

## GET /users/:id/reviews
`users.controller.ts:218` → `UsersService.getUserReviews` (`users.service.ts:583`) — REDB1-30.

- **Auth**: none (public).
- **Business rule**: 404 via `assertUserExists`. Aggregates `averageRating` and a 1★–5★ `breakdown` count (for the distribution bars) alongside the review list, in parallel queries. `boughtItem` is a comma-joined list of every listing title on the review's linked order (an order can carry multiple items — there is no single "the" item), `null` for the rare review whose order was later hard-deleted (`onDelete: SetNull` on the FK).
- **Response**: `{ data: ReviewDto[], averageRating, total, breakdown }`.
- **FRONTEND**: `usersApi.getUserReviews()` (public shop reviews tab) and, separately, `sellerApi.getReviews(userId)` on web (`seller/reviews/page.tsx`, reads `sellerApi.getMe()` first to get the caller's own id before fetching).

## POST /users/:id/follow
`users.controller.ts:224` → `UsersService.followUser` (`users.service.ts:513`) — BRI-65/95.

- **Auth**: `JwtAuthGuard`. `@HttpCode(201)`.
- **Business rules (`BR-USERS-025..030`)**:
  - Self-follow → 400 `'You cannot follow yourself.'`.
  - Target not found **or `target.suspended`** → **404** (not 403) — "a suspended account is hidden from browse and search, so for the follower it does not exist... not a 403 that would confirm the account is there and suspended" (BRI-468's fix, explicitly in-code).
  - **Target must be a confirmed seller** (`!target.isSeller` → 400 `'You can only follow a seller'`) — following is buyer→seller only (BRI-461's fix, explicitly in-code: "A buyer-only account has no shop and no listings to surface").
  - If the requester has **hidden** this seller (BRI-470, a buyer-side `Block` row with `blockedAsBuyer: true`) → 400 `"You've hidden this seller. Unhide them in Settings to follow."` — Follow and "hide this seller" are mutually exclusive states by design.
  - Already following → 409 `'Already following this user.'`.
  - **Follow takes effect immediately** — no seller-approval step (explicit Product Owner decision, 23 Jul 2026, per BRI-65/BRI-95's Linear description). The edge is created `status: 'accepted'` directly.
  - Two-sided counter increment in one `$transaction` (`Follow.create` + `followingCount++` on the follower + `followersCount++` on the followee), followed by a **realtime push** (`RealtimeGateway.emitToUser`, `'count:update'` event) to both parties so an open profile screen updates live without a refetch. The realtime push is best-effort (caught/logged, never fails the HTTP response).
- **DB**: 1 read (target lookup) + 1 read (hidden-seller check) + 1 read (existing-follow check) + `$transaction` of 3 writes + 1 read (pushCounts, re-fetches the changed user for the live payload) ×2.
- **Response**: `{ success: true, status: 'accepted' }` (the `status` field always reads `'accepted'` — there is no pending/rejected branch reachable from this endpoint, consistent with the "instant follow, no approval" product decision).
- **Linear — now-fixed bugs confirmed in code**: BRI-461 (buyer-only followable — code now blocks), BRI-468 (suspended user followable — code now blocks via 404). Both tickets still show status **"QA Testing"** in Linear as of this analysis, which is consistent with "fixed in code, pending QA verification/closure" rather than a contradiction.
- **FRONTEND**: `usersApi.followUser()`, driven by `followsStore.toggle()` (`apps/mobile/src/store/followsStore.ts`) — **optimistic update with NO request-ordering guard**: `toggle()` reads `wasFollowing`, flips local state immediately, then awaits the follow/unfollow call with no serialization against a second rapid tap on the same target. This is the **exact same shape** as the `likesStore` race that produced BRI-290 ("item removed after being added remains in wishlist") before it was fixed with a `pendingSync` promise-chain — `followsStore.ts` has **no such chain** (confirmed by reading the full file: no `pendingSync`/per-key promise-queue construct present). Per `apps/mobile/CLAUDE.md`'s own call-out: "`followsStore.toggle()` has the identical shape... and is very likely exposed to the same race — apply the same `pendingSync`-chain fix there under BRI-95". **Classify as an unpatched, reproducible race condition** — evidence: code read directly, cross-referenced against the already-fixed sibling (`likesStore.ts`) and the project's own documented intent to port the fix. See `identity.gaps.md` and `TS-USERS` concurrency scenarios.

## DELETE /users/:id/follow
`users.controller.ts:232` → `UsersService.unfollowUser` (`users.service.ts:551`)

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Business rule**: 404 `'You are not following this user.'` if no existing edge — this is a genuine user-facing error (contrast the internal `unfollowIfFollowing()` sibling method used by the hide-seller side effect, which silently no-ops instead). Reverses the exact two-sided counter decrement `createFollow` applied, via an underflow-safe Postgres `GREATEST(col - 1, 0)` raw update (never goes negative even against a pre-existing bad count).
- **DB**: 1 read (existing-follow check) + `$transaction` of 3 writes + realtime push ×2.
- **Response**: `{ success: true }`.
- **FRONTEND**: `usersApi.unfollowUser()`, same `followsStore.toggle()` call site and the same unpatched race as the follow direction above.

## POST /users/:id/report
`users.controller.ts:240` → `UsersService.reportUser` (`users.service.ts:577`)

- **Auth**: `JwtAuthGuard`. `@HttpCode(200)`.
- **Body** (`ReportUserDto`): `reason` (≤100, required), `note` (optional, ≤500).
- **Business rule**: self-report → 400 `'Cannot report yourself'`. Target existence checked (`assertUserExists`, 404 if not found) — **no suspended-check** (a suspended user can still be reported, unlike follow). Writes a `UserReport` row; no moderation/admin side effect traced in this batch (admin's consumption of `UserReport` is out of scope — `admin` module).
- **Response**: raw created `UserReport` row (the service returns `this.users.createUserReport(...)` directly — **not** passed through any DTO/allow-list mapper, unlike every other endpoint in this module). Worth flagging: this is the one `users`-module write endpoint whose response isn't shaped by a dedicated mapper — it returns whatever Prisma's `create()` gives back (full row, including `reporterId`/`targetId`/timestamps/`id`), which is harmless here (no sensitive fields on `UserReport`) but is an inconsistency with the rest of the module's response-shaping discipline.
- **FRONTEND — major mismatch found**:
  - **Mobile**: `apps/mobile/src/services/usersApi.ts` has **no wrapper at all** for `POST /users/:id/report` (confirmed: grep across `apps/mobile/src/services` for `/report` matches only the unrelated `/conversations/:id/report` in `messagingApi.ts` and `/sellers/me/seller-reviews/:id/report` in `sellersApi.ts`). The seller shop page's "•••" menu (`SellerOptionsSheet.tsx`, Figma 588-7794, REDB1-27) **does** render a "Report {sellerName}" row, and `ShopProfile.tsx`'s `handleReportPress()` (`ShopProfile.tsx:504-514`) shows a success toast ("Report sent — Thanks, our team will review this seller's shop") **without making any network call** — it is pure UI theater today. This is a real, user-facing false-success bug: a buyer who taps "Report" on a seller's shop page believes a report was filed; nothing reaches the server. Classify as **implemented-in-code (backend) / confirmed-absent (mobile frontend) / silent false-success (mobile UX)** — see `identity.gaps.md`.
  - **Web**: `sellerApi.reportUser(userId, reason, note)` (`apps/web/src/lib/sellerApi.ts:502-507`) **does** call this exact endpoint, used from `seller/followers/page.tsx:287` — a seller reporting one of their followers/reviewers from the Seller Portal. So the endpoint has exactly one real caller across both frontends, and it is the seller-portal side, not the mobile buyer-facing "Report seller" UI that visually advertises the feature.

---

## Account purge worker (not an HTTP endpoint — documented here because it is this module's terminal state transition)

`apps/api/src/users/account-purge.processor.ts`, bootstrapped only by `users-worker.module.ts` inside the separate worker process (`worker-main.ts`, never the API process — confirmed: `users.module.ts` the HTTP module does not import this processor or its queue). Runs hourly (`ACCOUNT_PURGE_CRON`, default `25 * * * *`) via a BullMQ job scheduler (`upsertJobScheduler`, idempotent across restarts), processing up to `ACCOUNT_PURGE_BATCH_SIZE` (default 50) accounts whose `deletionScheduledFor <= now` per tick.

- **Re-checks blockers a 4th time** at purge time — an account can still be deferred here (stays scheduled, retried next hour) if a blocker appeared during the 30/60-day window (e.g. a dispute opened on an old delivered order).
- **One account, one transaction** (30s timeout / 10s maxWait — explicitly sized after a real production transaction-timeout incident on a seller with many listings/followers/searches, per the code comment) — a failure on one account is logged and skipped, never rolls back or blocks the batch.
- **What survives**: a `DeletedAccountArchive` row (name/email/username/phone/role/wasSeller/reason/orderCount/lifetime-gross-cents, `retainUntil = purge-time + 7 years`) — the KYC/1099-K retention record. **Nothing currently deletes this archive row after the 7 years elapse** (BRI-598, Backlog, open as of this analysis — "Nothing ever deletes the archive record after the 7 years" is the ticket's own stated current behavior, matching the repository code directly: no purge-of-the-purge-record job exists anywhere in this codebase).
- **What's destroyed**: addresses, payment methods, likes, saved/recent searches, notifications, listing-events, category-affinity rows, all follow edges (with a bulk `GREATEST`-style counter repair on both sides — explicitly NOT a per-row loop, after an earlier production transaction-timeout on a popular account).
- **What's scrubbed, not deleted**: the `User` row itself — name→`'Deleted user'`, email→`deleted+<id>@deleted.redspur.invalid`, username→`deleted_<id>` (both rewritten rather than nulled, since both are `@unique`), password→an unusable random bcrypt hash (never an empty string — an empty hash makes `bcrypt.compare` throw, turning a clean "invalid credentials" into a 500), `suspended: true` set as a belt-and-braces measure alongside `deletedAt`. **Why scrubbed not deleted**: `Order`/`Payout`/`Review` hold FKs to `User`; cascading them away would destroy the *other* party's order history and the mandatory 1099-K substantiation.
- **Listings**: set to `status: 'inactive'` (not deleted) unless already `'sold'` (sold listings are the subject of a real order and must survive untouched).
- **Known open gaps per Linear, matching code as read**: BRI-620 (deleting a **seller** account never cancels open offers on their listings or closes their Stripe Connect account — Backlog, cross-reference only; this is seller-module-adjacent territory, flagged not deep-dived per the task's scope boundary) and BRI-672 (the Delete-Account **first screen's wording** claims the deletion "can't be undone" and that "order & message history" is removed — neither is literally true given the login-cancels-deletion restore path and the archive's retention of order counts/gross — Backlog, open copy bug, confirmed against `DeleteAccount.tsx`'s literal strings).

---

## Guard-application audit

| Route | Decorator present? | Verified at |
|---|---|---|
| `me/deletion/dev-code` is behind `JwtAuthGuard` **plus** a controller-level prod-environment 404 gate (not a guard class — an explicit `if` in the handler) | — | `users.controller.ts:140-147` |
| `me`, `me/preferences` (PATCH), `me/push-token` (POST/DELETE), `me/active`, `me/deletion` (GET/DELETE), `me/deletion/request`, `me/deletion/confirm`, `sellers`, `:id/likes`, `:id/follow` (POST/DELETE), `:id/report` | `@UseGuards(JwtAuthGuard)` | `users.controller.ts:27,35,46,57,72,87,104,116,127,141,156,168,196,226,234,242` |
| `:id` (GET), `:id/listings`, `:id/followers`, `:id/following`, `:id/reviews` | **No guard — public** | confirmed, no `@UseGuards` on these 5 methods |
| *(none)* | `RolesGuard`/`@Roles` | Not used anywhere in `UsersController` |
| *(none)* | `OptionalJwtAuthGuard` | Not referenced by this controller |
