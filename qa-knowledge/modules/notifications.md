# Module: notifications

4 endpoints, all under `@Controller('notifications')` with a class-level `@UseGuards(JwtAuthGuard)` — every route in this module requires a valid bearer token; there is no public or `OptionalJwtAuthGuard` route here (`apps/api/src/notifications/notifications.controller.ts:11-12`).

```
GET    /notifications            notifications.controller.ts:17-20
PATCH  /notifications/read-all   notifications.controller.ts:22-27
PATCH  /notifications/:id/read   notifications.controller.ts:29-34
POST   /notifications/delete     notifications.controller.ts:38-43
```

## Layer trace

**Controller → Service → Repository → Prisma**, no shortcuts. `NotificationsController` (`notifications.controller.ts`) takes `req.user.id` from the JWT and a DTO, delegates straight to `NotificationsService` (`notifications.service.ts`), which in turn calls `NotificationsRepository` (`notifications.repository.ts`) for all Prisma access. No controller or service touches `this.prisma` directly — consistent with `apps/api/CLAUDE.md`'s layering rule.

`NotificationsModule` (`notifications.module.ts:7-13`) imports `PrismaModule`, exports only `NotificationsService` — every other module that creates a notification (offers, orders, disputes, reviews, messaging, connect, sellers, auth, listings, payments, saved-searches — 11 service files reference `this.notifications.create/createRecord/pushIfEnabled`, confirmed via `grep -rn "notifications\.(create|createRecord|pushIfEnabled)" apps/api/src`) goes through this exported service, never the repository — correct module-boundary use.

### `GET /notifications` (`notifications.controller.ts:16-20`)

- Query DTO `GetNotificationsQueryDto` (`dto/get-notifications-query.dto.ts`): `page` (optional, `@Type(() => Number)`, `@IsInt`, `@Min(1)`, default 1) and `limit` (optional, same transform, `@Min(1)`, **`@Max(100)`**, default 20).
- `NotificationsService.getNotifications(userId, page, limit)` (`notifications.service.ts:45-48`) calls `repo.findByUserId` and returns `{ data, total, page, limit }` — a **plain offset-paginated list**, not cursor-based (consistent with `docs/architecture.md`'s "page/offset for stable lists" convention cited in `apps/api/CLAUDE.md`).
- `NotificationsRepository.findByUserId` (`notifications.repository.ts:19-31`) does `skip = (page-1)*limit`, orders `createdAt desc`, and runs the `findMany`+`count` as a `Promise.all` (one round trip for both). Backed by `@@index([userId, createdAt])` on `Notification` (`schema.prisma:1441`).
- **No unread-count-only endpoint exists.** The response has no `unreadCount` field at any layer — `unreadCount()` in the mobile store (`apps/mobile/src/store/notificationsStore.ts:111`) is computed **client-side** by filtering the already-fetched list (`notifications.filter(n => !n.read).length`). See Gaps.

### `PATCH /notifications/read-all` (`notifications.controller.ts:22-27`)

- No body. `markAllRead(userId)` → `repo.markAllRead(userId)` → `prisma.notification.updateMany({ where: { userId, read: false }, data: { read: true } })` (`notifications.repository.ts:33-35`).
- **Scoped to `userId` from the JWT only** — the `where` clause has no id/list input from the client at all, so there is structurally no way to mark another user's notifications read via this route. Verified safe (no cross-user leak possible by construction, not just by convention).
- Returns `{ success: true }` regardless of how many rows were actually flipped (idempotent — calling it with nothing unread is a no-op 200, not an error).

### `PATCH /notifications/:id/read` (`notifications.controller.ts:29-34`)

- `markOneRead(id, userId)` → `repo.markOneRead(id, userId)` → `updateMany({ where: { id, userId }, data: { read: true } })` (`notifications.repository.ts:37-39`).
- **Same-user scoping via the `where` clause**, not a prior ownership-check-then-404: an `id` belonging to another user silently matches zero rows and still returns `{ success: true }` — this endpoint **never 404s on a bad/foreign id**, it just reports success having changed nothing. Confirm this is intentional via a test (see Test Scenarios) — a caller cannot distinguish "already read," "not yours," and "doesn't exist" from the response alone.

### `POST /notifications/delete` (`notifications.controller.ts:36-43`)

- **Verb-as-path, by design, documented inline** (`notifications.controller.ts:36-37`): *"React Native drops the request body on DELETE, so the id list never reaches the server. A POST body is always transmitted."* Mirrored verbatim on the mobile side (`apps/mobile/src/services/notificationsApi.ts:31-32`).
- DTO `DeleteNotificationsDto` (`dto/delete-notifications.dto.ts`): `ids: string[]`, `@IsArray() @ArrayNotEmpty() @IsString({ each: true })` — an empty array is rejected by validation (400) before the service runs; there is no "delete nothing" 200 path via an empty body.
- `deleteNotifications(userId, ids)` → `repo.deleteMany(userId, ids)` → `prisma.notification.deleteMany({ where: { id: { in: ids }, userId } })` (`notifications.repository.ts:43-47`, comment confirms: *"Scoped to userId so a caller can only ever delete their own notifications, even if they pass another user's ids."*). Returns `{ success: true, deleted: <actual count> }` — **`deleted` can be less than `ids.length`** if some ids were already gone or belonged to another user; this is the one response in the module that tells the caller anything was partially ignored.
- This is a genuine hard delete (no soft-delete/`deletedAt` column on `Notification` — unlike `Listing`), consistent with notifications being disposable, not financial/audit records.

## Push delivery (`NotificationsService.sendPush`, `notifications.service.ts:65-107`)

Entered from three public methods with different push semantics:
- **`create(data)`** (`:12-22`) — persists via `repo.create`, then **always attempts** `sendPush` (subject to the preference gate below). This is what all 11 calling services use for a normal, preference-gated notification.
- **`createRecord(data)`** (`:25-33`) — persists only, **never** calls `sendPush`. For a caller that wants to decide push timing/suppression itself.
- **`pushIfEnabled(record, skipPush)`** (`:36-43`) — sends (gated) unless `skipPush` is true; pairs with `createRecord` for a caller that writes the row first and pushes conditionally later (e.g. suppressing a push for a conversation the recipient has open — see `apps/mobile/CLAUDE.md`'s BRI-391/REDB1-53 territory, which is `messaging`'s call site, not this module's).

`sendPush` (`:65-107`):
1. One combined read: `repo.findPushTarget(userId)` (`notifications.repository.ts:52-58`) returns `{ token: user.expoPushToken, prefs: user.notificationPrefs }` in a single `prisma.user.findUnique` — avoids two round trips for what every push needs.
2. **No token, or token doesn't start with `'ExponentPushToken'` → silently skip** (no error, no log). This is also how a signed-out device with a stale token is protected *in this code path* — though BRI-390/BRI-323/REDB1-57 (push still arriving after logout) establish that **token clearing/unregistration itself is not this module's job** — see `apps/mobile/src/services/notificationsApi.ts:49-50`'s `unregisterPushToken` (`DELETE /users/me/push-token`, owned by `users` module) and verify in the `identity` batch whether logout actually calls it on every exit path. This module only refuses to send to a token it still has on file; it cannot refuse a token it was never told to forget.
3. **Preference gate — `pushPrefKeyFor(type, data)` then `resolveNotificationPrefs(prefs)[prefKey]`** (`common/constants/notification-prefs.constant.ts:77-83`, see Business Rules below). If the type maps to a toggle and that toggle is off, the push is skipped — **but the in-app row was already written by `repo.create` before this check runs**, so a muted push type still appears in `GET /notifications` and in the Notification Center list. This is the documented BRI-521 contract (`notifications.service.ts:75-76`): *"the in-app notification row is still written by the caller — only the push stops."*
4. Expo push request: `POST https://exp.host/--/api/v2/push/send`, body includes `data: { ...data, type }` (so the client can route a tap — BRI-425) and **`channelId: 'default'`, `priority: 'high'`** (BRI-389: without this, Android routes to its own default-importance "Miscellaneous" channel and the push never shows a heads-up banner — must match the channel the mobile app itself creates at `AndroidImportance.MAX`, `apps/mobile/src/services/pushNotifications.ts:40-46`).
5. **Never throws.** Both the Expo HTTP error-status case and a network-level `fetch` rejection are caught and only `logger.warn`'d (`:101-106`). A push failure never fails the notification-creating request (e.g. accepting an offer never 500s because Expo is down).

## Notification type taxonomy (`NotificationType` enum, `schema.prisma:128-184`, 35 members)

Cross-referenced against `common/constants/notification-prefs.constant.ts`'s `pushPrefKeyFor` (`:77-83`), which is the **only** place that decides push-gating by type:

| Toggle key (`NOTIFICATION_PREF_KEYS`) | Default | Types routed to it |
|---|---|---|
| `offersMessages` | ON | `new_offer`, `offer_accepted`, `offer_declined`, `offer_expired`, `message_received` |
| `orderUpdates` | ON | `order_placed`, `order_cancelled`, `order_shipped`, `order_delivered`, `order_returned`, `order_delivery_failed`, `review_received` — **only when `data.role !== 'selling'`** |
| `sellerAlerts` | ON | same order-type set as above — **only when `data.role === 'selling'`** |
| `priceDrops` | ON | `price_drop` |
| `newFromFollowed` | ON | `followed_seller_listing` |
| `emailReceipts` | ON | *(no push mapping — email-channel only; this module has no email send path, see Gaps)* |
| `marketing` | **OFF** (the one opt-in default) | *(no push mapping — email-channel only, same as above)* |

**Always-send types (no toggle governs them, `pushPrefKeyFor` returns `null`)**: `listing_approved`, `listing_rejected`, `listing_pending`, `payment_failed`, `follow_request`, `follow_accepted`, `saved_search_match`, `dispute_opened`, `dispute_evidence_submitted`, `dispute_approved`, `dispute_denied`, `dispute_withdrawn`, `dispute_refunded`, `stripe_dispute_created`, `stripe_dispute_resolved`, `stripe_reversal_failed`, `stripe_account_deauthorized`, `stripe_account_restricted`, `stripe_account_rejected`, `dispute_refund_failed`, `shippo_purchase_failed`, `new_device_signin` — documented rationale (`notification-prefs.constant.ts:69-76`): security alerts, payment failures, disputes/chargebacks, listing moderation, and saved-search matches (which have their own per-search `alertsEnabled` switch on `SavedSearch`, not a global toggle) always send regardless of the Settings screen.

**In-app-only vs push-eligible**: every `NotificationType` is written to the `Notification` table identically (there is no type-level flag for "in-app only") — the push/in-app split is entirely about whether `sendPush` is reached and whether the preference gate passes, not about the type itself. So in this codebase there is no genuinely "push-only" notification (every push has a matching row), but every type is "in-app guaranteed, push conditional."

**Role-based routing nuance**: `pushPrefKeyFor`'s order-type branch keys off `data?.role === 'selling'`, i.e. it trusts the caller to stamp `role` correctly on the notification's own `data` payload at creation time (see `offers.service.ts` call sites, e.g. `notifications.create({ ..., data: { offerId, role: 'selling' } })`). A caller that forgets to stamp `role` on an order-type notification silently falls through to `orderUpdates` (buyer toggle) even if the recipient is actually the seller — worth testing (see TS-NOTIFICATIONS-010).

## Business rules

See `qa-knowledge/fragments/notifications-support.business-rules.json` for the structured `BR-NOTIFICATIONS-*` list (push gating, scoping, pagination cap, delete semantics, type taxonomy).

## Frontend usage (mobile)

- **`apps/mobile/src/services/notificationsApi.ts`** — thin wrapper over the four endpoints plus the two `users/me/push-token` routes (owned by `identity`, cross-referenced not duplicated here).
- **`apps/mobile/src/store/notificationsStore.ts`** — single Zustand store, `NOTIFICATIONS_FETCH_LIMIT = 100` (`:16`, hard capped by the DTO's `@Max(100)` — raising this constant above 100 silently breaks the Inbox with no error, per the store's own comment). `loadNotifications()` fetches page 1 at that limit (no further pagination in the UI — the Inbox has no infinite scroll). **Optimistic `read` is sticky-OR'd with the server's value** (`:53,61`) to survive a refetch race against an in-flight `markOneRead`/`markAllRead` PATCH (documented BRI-382 fix). `markOneRead`/`markAllRead`/`deleteNotifications` are all optimistic-with-rollback.
- **No dedicated unread-count endpoint or store selector beyond a local `.filter()`** — `unreadCount()` (`notificationsStore.ts:111`), `MyProfile.tsx`'s row count (`:89`), and `InboxHome.tsx`'s Offers-tab dot (via `isOfferNotification`, `utils/notificationRole.ts:44-48`) all derive from the full 100-row list already loaded into the store, not a server count. Each of the three surfaces independently calls `loadNotifications()` on its own `useFocusEffect` (`MyProfile.tsx:74-79`, `InboxHome.tsx:206-210`, `Notifications.tsx:60-64`) — there is no shared polling/subscription, no WebSocket push of new-notification events into this store (the `messaging`/`realtime` gateways are a separate concern — out of scope for this batch).
- **`screens/inbox/Notifications.tsx`** is the only in-app list view (lifted out of `InboxHome`'s tabs per its own doc comment, `:22-36`) — owns `openNotification`'s per-type routing table (`:86-194`), multi-select delete flow, and the seller/buyer `RoleTabs` split via `notificationRole()` (`utils/notificationRole.ts:50-62`, which prefers the server-stamped `data.role`, falls back to the linked offer's direction, then falls back to a static type-set `SELLING_NOTIF_TYPES`).
- **`navigation/notificationRoute.ts`** (`openNotificationFromRoot`) is a **second, independently-maintained copy** of the same per-type routing switch, for taps arriving with no screen-local navigation prop (backgrounded/killed-app pushes). Its own doc comment (`:14-16`) states it must be kept in sync with `Notifications.tsx`'s `openNotification` by hand — there is no shared table; a new type added to one and not the other is a real regression class (see Gaps).
- **`screens/profile/NotificationSettings.tsx`** — the preference toggles UI (BRI-521), calls `usersApi.updatePreferences({ notifications: { [key]: value } }, token)` → `PATCH /users/me/preferences` (owned by `identity`). Per-key `useRef` latch (`inFlight.current`) prevents a double-tap race; optimistic with rollback-and-alert on failure.
- **`services/pushNotifications.ts`** — device-side token registration (`registerPushToken`, skipped in Expo Go/non-devices), the Android `default` channel creation at `AndroidImportance.MAX` (must match the server's `channelId: 'default'`), and `dismissNotificationsForConversation` (BRI-391, clears OS-level notifications tied to a conversation once read — only for `message_received`-shaped data, not a general-purpose dismiss).

## Known prior incidents (grounding, not re-derived)

- **BRI-382** ("Inbox badge does not clear") — the actual bottom-nav Inbox badge was removed outright by the 2.0 nav redesign (`9b63a3ac`); the ticket kept getting "fixed" for a UI element that no longer exists. The real gaps were `MyProfile.tsx`'s Notifications row count and `InboxHome.tsx`'s Offers-tab dot not independently refetching — fixed via per-screen `useFocusEffect` (`apps/mobile/CLAUDE.md`'s own write-up, and confirmed directly in both screens' source above).
- **BRI-521** — toggles didn't persist (local state only); fixed by routing through `PATCH /users/me/preferences` + the server checking `notification-prefs.constant.ts` before every push. **Status in Linear as of this analysis: `REDB1-40` (the Baseline-1 copy of BRI-521) is `Reopened`, assigned to `Ahsan`** — this analysis's code trace shows the mechanism exists and is unit-tested (`notifications.service.spec.ts:119-126`, `notification-prefs.constant.spec.ts`), so if REDB1-40 is still open, confirm with QA whether it's a regression, a different toggle than the ones fixed, or a stale ticket (same "ticket describes a UI element/behavior that may already be fixed" trap `apps/mobile/CLAUDE.md` calls out for BRI-382).
- **BRI-389/BRI-388** (Android push arrives silently, no heads-up banner) — fixed via the `channelId: 'default'` + `priority: 'high'` pairing (service + `notifications.service.spec.ts:86-98`), both sides `QA verified`.
- **BRI-391 / REDB1-69** (opening a conversation only dismisses the tapped notification, not the whole thread) — fixed via `dismissNotificationsForConversation`; REDB1-69 (Baseline-1 copy) is `Reopened` as of this analysis — worth a regression pass.
- **BRI-390 / BRI-323 / REDB1-57** (signed-out device keeps receiving the previous account's pushes) — this module's own code (`sendPush`) only refuses a token it doesn't have on file; the fix is in token *unregistration* on logout, outside this module's boundary (likely `identity`/`auth`). REDB1-57 is `QA Passed`.
- **REDB1-70** (tapping a push with the app killed opens Home, not the related screen, though backgrounded works) — implicates `notificationRoute.ts`'s `openNotificationFromRoot` / `App.tsx`'s `getLastNotificationResponse` wiring, not the server. `QA Passed`.
- **REDB1-134** (tapping a seller's message push opens the buyer chat context; Back returns to buyer Inbox) — routing-table/navigation-context bug in the client's notification-tap path, `Todo`.
- **REDB1-53** (`message_received` push not suppressed while the recipient is viewing that thread) — a `pushIfEnabled`/`skipPush` candidate (the mechanism exists in this module) but the actual suppression decision belongs to `messaging`'s call site. `Backlog`.
