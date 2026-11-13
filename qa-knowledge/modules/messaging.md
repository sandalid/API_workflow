# Module: messaging

**Scope**: `apps/api/src/messaging/` (21 REST routes: `messaging.controller.ts` + `messaging.admin.controller.ts`) plus two WebSocket gateways (`apps/api/src/messaging/messaging.gateway.ts` namespace `/ws/chat`, `apps/api/src/realtime/realtime.gateway.ts` namespace `/ws/user`). Frontend consumers: `apps/mobile/src/services/messagingApi.ts` + `chatSocket.ts` + `components/chat/**` + `screens/inbox/**`; `apps/web/src/lib/api.ts`'s `adminApi` messaging methods + `apps/web/src/app/admin/messages/**`; `apps/web/src/lib/useUserSocket.ts` (realtime gateway only, seller portal).

**Primary reference docs read first**: repo-root `messaging.md` (phase-by-phase build log — **stale on the block/unblock feature, which postdates it**; treat its Phase 1–8 content as historically accurate but cross-check anything block-related against the actual source below), `apps/mobile/CLAUDE.md` (BRI-382 history), `apps/api/CLAUDE.md` (guard patterns, CORS triplication, layering rules).

**Data model** (`apps/api/prisma/schema.prisma:222-240, 1807-1915`): `Conversation`, `Message`, `ConversationReport`, `Block`, enums `ConversationStatus{active,archived,admin_locked}`, `ConversationReportReason{harassment,scam,spam,offensive,other}`, `ConversationReportStatus{open,resolved,dismissed}`. `User` carries `chatBanUntil DateTime?` and `chatWarningCount Int @default(0)`.

---

## 1. Buyer/seller REST routes (`messaging.controller.ts`, class-level `@UseGuards(JwtAuthGuard)`)

### `POST /conversations` (messaging.controller.ts:33-40)
- **DTO** `CreateConversationDto` (dto/create-conversation.dto.ts): `sellerId?`, `listingId?` — at least one required via `@ValidateIf` cross-field logic (conditionally-required, not a DTO-level `@IsNotEmpty` on either). Fixed historical bug BRI-498 ("Conversation cannot be started with only a listingId").
- **Service** `createConversation` (messaging.service.ts:125-191):
  1. 404 if caller doesn't exist.
  2. 403 `CHAT_BANNED` if `caller.chatBanUntil > now`.
  3. If `listingId` given: 404 if listing doesn't exist; 403 if `listing.sellerId === callerId` (can't message yourself about your own listing).
  4. `sellerId` resolves to `dto.sellerId ?? listing.sellerId`; 400 if `callerId === sellerId`.
  5. 404 if seller doesn't exist.
  6. **No block check at all** — a blocked pair can still create a conversation row; see BR-MESSAGING-011.
  7. Idempotent creation: non-null `listingId` → `upsertConversation` (Prisma `upsert` on the composite unique); null `listingId` → explicit `findFirst` guard (Postgres treats composite-unique NULLs as distinct rows) then `createConversation`, with a P2002-catch-and-refetch race guard in both branches.
  8. Response always shaped via `shapeConversation` (fixed historical bug BRI-498 follow-up — every path previously returned a raw Prisma row missing `otherUser`).
- **Guards**: `JwtAuthGuard` only (class-level).
- **AllExceptionsFilter interaction**: `HttpException({code:'CHAT_BANNED', until, message}, 403)` passes through the filter's generic 4xx shaping untouched (the filter doesn't strip custom body fields for `HttpException`-derived throws) — the mobile client reads `err.code`/`err.until`.

### `POST /sellers/me/orders/:id/conversation` (messaging.controller.ts:42-52)
- **Guards**: `JwtAuthGuard` (class) + `RolesGuard` + `@Roles('SELLER')` (method-level) — per `apps/api/CLAUDE.md`, `RolesGuard` checks `'SELLER'` live against the DB (`isSeller`), so a mid-session seller confirmation takes effect immediately.
- **Service** `createConversationAsSeller` (messaging.service.ts:200-225): loads the order via `OrdersService.findById(orderId, callerId)`; 403 if `order.sellerId !== callerId` (ownership re-check beyond the role guard). Ban-checked identically to the buyer path. Reuses an existing `(buyerId=order.buyerId, sellerId=callerId, listingId=null)` conversation if one exists, else creates it. **No `listingId` is ever attached** — this is post-order contact, not a pre-purchase listing inquiry, so it can't collide with/merge into a listing-anchored thread.
- This is the ONLY way a seller can originate a thread; `createConversation` always makes the caller the buyer.

### `GET /me/conversations` (messaging.controller.ts:54-61)
- **DTO** `ListConversationsQueryDto`: `cursor?`, `limit?` (1-50, default 20).
- **Repository** `listConversations` (messaging.repository.ts:306-363): cursor pagination on `(lastMessageAt desc, id desc)`, opaque base64 cursor. Excludes: conversations the caller has soft-deleted (`deletedByBuyer`/`deletedBySeller`) and conversations whose other participant the caller has blocked (`getBlockedIds`). Uses `MOBILE_CONVERSATION_SELECT` (no `_count` — that's admin-only, avoids correlated subqueries on every inbox load) plus one extra nested query per row batch for the "latest referenced listing" rule (BR-MESSAGING-025), not one query per row.
- Response shaped per-row via `shapeConversation` → `{id, status, role, lastMessageAt, lastMessagePreview, unreadCount, otherUser, listing, createdAt, blockedByMe}`. **`blockedByMe` is always `false` here** (default param) — see `GET /conversations/:id` below for why.

### `GET /conversations/:id` (messaging.controller.ts:63-70)
- **Authorization**: participant OR `req.user.role === 'ADMIN'` (messaging.service.ts:241-243) — this is a second, less-restricted admin path into conversation data beyond `/admin/conversations/:id`, reachable by any admin JWT even without going through the admin controller.
- Computes and returns two fields the list endpoint omits: `blockedByMe` (via `repo.isBlocked(callerId, otherUserId)` — the ONLY way the chat screen learns the caller blocked the other side, since a blocked thread is filtered out of the list) and `isFirstContactWithUser` (via `repo.hasPriorMessageBetween`, role-agnostic, account-pair-scoped not thread-scoped — BRI-64's safety-banner rule).
- Also resolves `findLatestReferencedListing` and swaps it into the `listing` field if present (BR-MESSAGING-025).

### `GET /conversations/:id/messages` (messaging.controller.ts:72-80)
- Reuses `ListConversationsQueryDto` for `cursor`/`limit` (a mild DTO-reuse smell — same shape, different resource, acceptable).
- **Authorization**: participant only (NOT admin — unlike `GET /conversations/:id`, this route has no role bypass; an admin must use `GET /admin/conversations/:id/messages` instead).
- **Repository** `listMessages` (messaging.repository.ts:423-456): keyset pagination on `(createdAt desc, id desc)`, results reversed back to chronological order before return. Soft-removed messages (`deletedAt` set) stay in the result set — the client renders "Removed by moderator" rather than the thread reflowing.

### `POST /conversations/:id/messages` (messaging.controller.ts:82-91)
The highest-complexity route. **Service** `sendMessage` (messaging.service.ts:276-374), in order:
1. 404 if conversation doesn't exist; 403 if caller isn't a participant (no admin bypass here either).
2. 404 if caller user record missing.
3. 403 `CHAT_BANNED` if banned.
4. 403 `CONVERSATION_LOCKED` if `status === admin_locked`.
5. Both directions of block checked: 403 `BLOCKED_BY_ME` if caller blocked recipient; 403 `RECIPIENT_BLOCKED` if recipient blocked caller (message text never reveals who blocked whom).
6. `resolveReferences` — buyer-only in-thread references (403 ForbiddenException if a seller tries); validates `listingRefId` belongs to the conversation's seller, `orderRefId` belongs to the conversation's buyer+seller pair.
7. `classify(dto.body)` — content filter. `payment` → 403 `OFF_PLATFORM_PAYMENT` (message never persisted). `contact` → 403 `CONTACT_BLOCKED` (never persisted). Anything else flagged (profanity, bare URL) does NOT block — message is created with `isFlagged=true`, `flagReasons[]` populated, and delivered normally.
8. `createMessage` — single `$transaction`: insert `Message` + bump `Conversation.lastMessageAt`/`lastMessagePreview` (140-char truncation) + increment the recipient's unread counter + reset both `deletedByBuyer`/`deletedBySeller` to `false` (resurfaces a soft-deleted thread for whichever side had hidden it).
9. Fire-and-forget (not awaited into the response): `NotificationsService.createRecord` (always writes a `message_received` Notification row) `.then(pushIfEnabled(...))` gated on `gateway.isUserActiveOnConversation` — push is skipped only if actively viewing, the DB record is never skipped. Failure here is logged, not thrown (message already saved/delivered).
10. If the gateway is wired (it's `@Optional()` — absent in some test contexts), emits `message:new` to both participants' rooms and `conversation:updated` (partial snapshot, no extra query) to both.
- **Response shape** (`shapeMessage`): flattens `listingRef`/`orderRef` into lightweight preview cards; `null` for both on a plain text message.

### `PATCH /conversations/:id/read` (messaging.controller.ts:93-101)
- **Service** `markRead` (messaging.service.ts:413-428): 404/403 same participant checks. `repo.markRead` — single `$transaction`: zero the caller's unread counter + set `readAt` on every message in the thread sent by the OTHER party that's still unread (used for the mobile "Read {relative time}" receipt on the sender's own bubbles). Emits `message:read` to the other participant via the gateway if present.
- **This is conversation read-state, NOT notification read-state** — see BR-MESSAGING-027. It has no effect on the separate `Notification.read` field.

### `POST /conversations/:id/report` (messaging.controller.ts:103-112)
- **DTO** `ReportConversationDto`: `reason` (enum, required), `note?` (≤500 chars).
- **Service** `reportConversation` (messaging.service.ts:430-446): participant check, then 400 BadRequestException if the caller already has an OPEN report on this conversation (rate-limited to one open report per reporter-per-conversation, not per time window). Creates a `ConversationReport` row, `status: open` by default.

### `DELETE /conversations/:id` (messaging.controller.ts:114-122)
- **Service** `deleteConversation` (messaging.service.ts:557-565): per-user soft delete only (`deletedByBuyer`/`deletedBySeller`), see BR-MESSAGING-023. The other participant's view is completely unaffected.

### `POST /conversations/:id/block` (messaging.controller.ts:124-132)
- **Service** `blockFromConversation` (messaging.service.ts:567-586): derives `context` (`'buyer'`/`'seller'`) from the caller's own role in THIS conversation — no client input needed. Soft-deletes the thread for the caller (same mechanism as plain delete, same role param) + `createBlock` (upserts the `Block` row, setting only the relevant `blockedAsBuyer`/`blockedAsSeller` flag — both can independently be true if blocked from both capacities over time) + `OffersService.cancelOffersBetween(buyerId, sellerId)` (silent, no notification to the other side — "no money has moved on a still-open offer, so it's safe to withdraw").
- **Not documented in the repo-root `messaging.md`** (predates this feature) — this is the authoritative source.

### `GET /me/blocked-users` (messaging.controller.ts:138-145)
- **DTO** `BlockedUsersQueryDto`: optional `context` (`'buyer'|'seller'`). Omitted → both sides' blocks. Powers the buyer Settings and Seller Hub Settings "Blocked users" screens off the same endpoint, filtered by context (BRI-170).
- Response: `{data: [{id, username, displayName, avatarUrl, blockedAt}]}`. Deleted-account blocked-ids are silently skipped (the `Block` row has no FK to `User`, so a stale row can't be joined).

### `POST /me/blocked-users/:userId` (messaging.controller.ts:150-159)
- **DTO** `BlockUserQueryDto`: `context` REQUIRED here (unlike the other block endpoints, which derive it) — there's no conversation to infer it from.
- **Service** `blockUser` (messaging.service.ts:600-617): standalone block outside any conversation ("Also hide this seller" on a listing-report confirmation, BRI-470). Same `Block` row mechanism as the in-conversation block. Also cancels open offers between the pair, and if `context==='buyer'`, unfollows the blocked seller if currently followed.

### `DELETE /me/blocked-users/:userId` (messaging.controller.ts:165-173)
- **Service** `unblockUser` (messaging.service.ts:647-661): one-way (only lifts the CALLER'S own block, 404 if none exists), optionally scoped by `?context`. Restores (un-hides) every shared conversation on the lifted side.

---

## 2. Admin REST routes (`messaging.admin.controller.ts`, class-level `@UseGuards(JwtAuthGuard, RolesGuard)` + `@Roles('ADMIN')`)

Per `apps/api/CLAUDE.md`, `RolesGuard` checks `ADMIN` against the **JWT's role claim directly** (not a live DB re-check, unlike `'SELLER'`) — an admin's access is only as fresh as their last token issue.

### `GET /admin/conversations` (messaging.admin.controller.ts:32-36)
- **DTO** `AdminListConversationsQueryDto`: `cursor?`, `q?` (free-text buyer/seller name/username search, case-insensitive), `flagged?` (has any flagged message), `hasReport?` (has an open `ConversationReport`), `status?`, `limit?` (1-100).
- **Repository** `adminListConversations` (messaging.repository.ts:365-415): full `CONVERSATION_SELECT` (includes `_count` of open reports + flagged messages, driving the list's flag/report dot indicators).

### `GET /admin/conversations/:id` (messaging.admin.controller.ts:38-42)
- Plain 404-or-row, no participant check (admin-only route by class guard).

### `GET /admin/conversations/:id/messages` (messaging.admin.controller.ts:44-51)
- Same `listMessages` repository call as the buyer/seller route, no ban/lock/block gating (admins read everything, including removed-message bodies via the raw row — `shapeMessage` still nulls the body text behind `removed` handling only on the CLIENT side; the admin route's underlying message IS un-redacted in the DB, but `adminGetMessages` reuses the same `shapeMessage` as the buyer path, which does NOT special-case `deletedAt` — **the admin UI must separately decide to show the real `body` or honor `deletedAt` itself**; verify in the web page before assuming admins see the "real text" automatically through this specific route).

### `GET /admin/messages/flagged` (messaging.admin.controller.ts:53-57)
- **DTO** `AdminListFlaggedMessagesQueryDto`: `cursor?`, `reason?` (filters `flagReasons has <reason>`), `limit?` (1-100).
- Excludes soft-removed messages (`deletedAt: null` in the where clause) — once removed, a message drops out of this queue even if still flagged.

### `POST /admin/messages/:id/remove` (messaging.admin.controller.ts:59-67)
- **Service** `adminRemoveMessage` (messaging.service.ts:485-497): 404 if message missing, 400 if already removed (no double-remove, no un-remove). Soft-delete only (BR-MESSAGING-019).

### `GET /admin/conversation-reports` (messaging.admin.controller.ts:69-73)
- **DTO** `AdminListReportsQueryDto`: `status?`, `conversationId?` — no pagination (returns the full matching set; acceptable at current report volume, a scale risk if report volume grows — not cursor-paginated unlike every other list route in this module).

### `POST /admin/conversation-reports/:id/resolve` (messaging.admin.controller.ts:75-84)
- **DTO** `ResolveReportDto`: `action` (`dismiss|warn|suspend|ban`, required), `durationDays?` (required-if-suspend, ≥1), `targetUserId` (required — the admin, not the server, decides who the action targets; the web UI defaults it to "whichever of buyer/seller is NOT the reporter" but the API trusts the body value as-is with no validation that `targetUserId` is actually a participant in the conversation), `lockConversation?`.
- **Service** `resolveReport` (messaging.service.ts:499-536) → **Repository** `resolveReport` (messaging.repository.ts:772-896), one `$transaction`:
  - 404 if report missing; 400 if already resolved/dismissed (no re-resolve).
  - `dismiss`: status → `dismissed`, zero side effects.
  - `warn`: `chatWarningCount++` on `targetUserId`, system message posted to the conversation ("A moderator has issued a warning..."), **auto-escalates to a 100-year ban + second system message if the count reaches 3**.
  - `suspend`: requires `durationDays`; sets `chatBanUntil = now + durationDays`, system message posted.
  - `ban`: sets `chatBanUntil = now + 100 years`, system message posted; if `lockConversation` was ALSO passed, sets `status = admin_locked` + a THIRD system message. **`lockConversation` is silently ignored for `warn`/`suspend`/`dismiss`** — confirmed gap, BRI-562.
  - All system messages are plain `Message` rows with `isSystemMessage: true`, visible to BOTH participants (not addressed to just the target) — copy like "You have been permanently banned..." reads oddly to the OTHER participant, also confirmed as a gap in BRI-562.
  - No notification is sent to the targeted user for ANY of these actions — they only discover it via a failed send (BR-MESSAGING-015/016 territory) or by reading the system message if they happen to be in the thread.

### `POST /admin/users/:id/chat-ban` (messaging.admin.controller.ts:86-94)
- **DTO** `ChatBanDto`: `until?` (ISO date), `permanent?` (boolean) — 400 if neither provided.
- **Service** `adminChatBan` (messaging.service.ts:538-554): direct `chatBanUntil` write, no conversation context, no system message, no notification, no report interaction. This is the endpoint the admin web's "Direct Actions" sidebar buttons call for Suspend 7d/30d/Permanent ban — see BR-MESSAGING-020 for how this diverges from the Resolve-Report path despite similar-looking UI.

---

## 3. WebSocket gateway — `MessagingGateway` (`apps/api/src/messaging/messaging.gateway.ts`, namespace `/ws/chat`)

- **Handshake/auth**: JWT passed as `socket.handshake.auth.token` (NOT an `Authorization` header). `handleConnection` verifies with the same `JwtService`/`JWT_SECRET` as the HTTP `JwtAuthGuard`. **Fails closed**: an unconfigured/empty `jwtSecret` disconnects every connection attempt rather than accepting unauthenticated sockets (logged as `error`, not silently open). An invalid or missing token also disconnects (logged as `warn`).
- **Rooms**: every authenticated socket joins `user:{userId}` — no per-conversation room; all targeting is "to this user's room," so a user's multiple devices/tabs all receive the same events.
- **CORS**: reads `process.env.CORS_ORIGINS` directly at class-load time (documented exception in `apps/api/CLAUDE.md` — Nest DI isn't ready yet when the `@WebSocketGateway()` decorator's config object is evaluated); must be kept in sync with `main.ts` and `realtime.gateway.ts` manually.
- **Server → client events**:
  | Event | Payload | Trigger |
  |---|---|---|
  | `message:new` | shaped `Message` (via `shapeMessage`) | `sendMessage` success — emitted to BOTH the recipient's room and the sender's own room (so other devices/tabs of the sender see it too) |
  | `conversation:updated` | `{id, lastMessageAt, lastMessagePreview, buyerUnreadCount, sellerUnreadCount}` (partial, no re-query) | `sendMessage` success — emitted to both participants' rooms |
  | `message:read` | `{conversationId, readerId}` | `markRead` success — emitted to the OTHER participant's room only |
  | `typing:update` | `{conversationId, userId, isTyping}` | relay of client's `chat:typing` — emitted to the named `recipientId`'s room only, no persistence |
- **Client → server events** (`@SubscribeMessage`):
  | Event | Payload | Effect |
  |---|---|---|
  | `chat:focus` | `conversationId` (string) | records `socketId → conversationId` in `focusMap`; clears any pending reconnect-grace entry for this user |
  | `chat:blur` | — | removes the `focusMap` entry; clears reconnect grace immediately (explicit navigate-away, not a drop) |
  | `chat:typing` | `{conversationId, recipientId, isTyping}` | pure relay, no DB write, no persistence — requires `socket.data.userId` to be set (post-auth) |
- **No client → server message-send event exists** — HTTP `POST /conversations/:id/messages` is the only write path; the gateway is push-only for content, bidirectional only for focus/typing signaling.
- **`isUserActiveOnConversation(userId, convId)`**: true if ANY of the user's currently-connected sockets is focused on `convId`, OR their last socket on that conversation disconnected within the last 15s (`RECONNECT_GRACE_MS`) without an explicit `chat:blur` since (BRI-384 — covers a transport reconnect/Android-doze blip without leaking a push mid-session). Used exclusively to gate Expo push suppression in `MessagingService.sendMessage` — it never gates the DB `Notification` record itself.
- **Reconnect self-healing** (mobile side, `chatSocket.ts`): on every `connect` event (including reconnects), the client re-emits `chat:focus` for whatever conversation it was last on and refetches `GET /me/conversations` — covers the case where a `message:new`/badge-count event was missed entirely during the drop (socket.io does not replay missed events).

## 4. WebSocket gateway — `RealtimeGateway` (`apps/api/src/realtime/realtime.gateway.ts`, namespace `/ws/user`)

- **Not part of the chat feature** — a separate, generic per-user push channel. Same JWT-over-`handshake.auth.token` auth pattern, same `user:{userId}` room join, same fail-closed-on-misconfig behavior, independently reads `process.env.CORS_ORIGINS`.
- **Only consumer found**: `apps/web/src/lib/useUserSocket.ts` (seller portal), subscribing to `follow:request` (`FollowEventPayload`) and `count:update` (`CountUpdatePayload`, denormalized follower/following tallies) — purely additive over a 30s poll baseline, per `apps/web/CLAUDE.md`. No messaging-module code publishes to this gateway and no mobile code subscribes to it for chat purposes. `emitToUser`/`broadcastAll` are its only public methods; it's exported from `RealtimeModule` for any domain module to inject.
- Mentioned here only because the task scope named it explicitly — **do not confuse it with `MessagingGateway`** when writing test scenarios; they are fully independent namespaces/servers with no shared state.

---

## 5. Mobile frontend (`apps/mobile/src`)

- **`services/messagingApi.ts`**: thin `request<T>()` wrappers, one per endpoint, 1:1 with the REST surface above (including all three block endpoints). No client-side retry.
- **`services/chatSocket.ts`**: singleton `socket.io-client`, connects to `${apiWsUrl()}/ws/chat`. `auth` is a FUNCTION (not a static object) specifically so socket.io calls it fresh on every reconnection attempt — a static token would go stale forever after the access token rotates mid-session (silent-refresh in `apiClient`) and the transport later drops/reconnects (BRI-426 regression class). Binds all four server events to `messagesStore` actions (`appendMessage`, `applyConversationUpdated`, `applyMessageRead`, `setTyping`).
- **`store/messagesStore.ts`**: `HARD_BLOCK_CODES = ['OFF_PLATFORM_PAYMENT','CONTACT_BLOCKED','CHAT_BANNED','RECIPIENT_BLOCKED','BLOCKED_BY_ME']` — any of these on a send failure drops the optimistic bubble entirely rather than offering "Tap to retry" (retrying is guaranteed to fail identically for all five). Anything else gets the generic `sendStatus:'failed'` + retry affordance. Optimistic send with `temp-<timestamp>` id, replaced on success; `markRead` is optimistic and never rolled back (fixed BRI-382's stale-badge class of bug). `blockedByMeByConv`/`unsendableByConv` track the two distinct block-outcome states client-side (own block vs. being blocked, never conflated per `useChatComposer`/`Chat.tsx`'s banner logic).
- **`hooks/useChatComposer.ts`**: shared send/retry/typing pipeline used by both the buyer Chat screen and (per its own doc comment) a seller-hub chat screen, specifically so the gate-and-deliver logic can't drift between the two. Client-side `classifyContent` pre-empts payment/contact sends before the round trip (same two hard-blocked categories as the server); the server's `classify()` call is still authoritative and the only check an API caller can't bypass.
- **`components/chat/`**: `BlockUserModal` (confirm-before-block, "Block {name}?"), `ChatOptionsSheet` (report/block/unblock entry), `MessageBlockedSheet` (3 variants: `payment`, `contact` — both offer "Edit message"; `unavailable` — neutral "can't send messages here" copy with no attribution, for `RECIPIENT_BLOCKED`), `ReportConversationSheet`, `AddToMessageSheet`/`ReferenceListingSheet`/`ReferenceOrderSheet` (buyer-only reference-attach flow), `MessageReferenceCard` (renders the flattened preview), `TypingDots`, `SafeTradingInfoSheet`.
- **`screens/inbox/Chat.tsx`**: on focus, loads messages + conversation detail (for `blockedByMe`/lock/first-contact) + marks read + emits `chat:focus`; on blur emits `chat:blur`. Composer disabled state is the union of `isBanned || isLocked || creatingConv || isUnsendable || blockedByMe`, each with distinct banner copy (ban banner shows the readable-until-100-years-away date per BRI-679's still-open gap; locked banner; "you blocked them" banner with an Unblock link; neutral "can't send here" banner for being blocked, with NO unblock option since the caller can't lift someone else's block).
- **`screens/inbox/InboxHome.tsx`**: Messages tab unread dot reads `conversations[].unreadCount` (conversation read-state); Offers tab dot reads `notifications[]` filtered by `isOfferNotification()` (notification read-state) — see BR-MESSAGING-027, these are deliberately different data sources and must not be conflated when writing test assertions.

## 6. Web frontend (`apps/web/src`)

- **`lib/api.ts`**'s `adminApi` messaging section (~line 476 on): 1:1 wrappers for all 9 admin endpoints. No websocket consumption for messaging admin — the admin UI is pure poll/refetch-on-action, matching `apps/web/CLAUDE.md`'s "poll as source of truth" convention; `useUserSocket.ts` is unrelated (realtime gateway, seller portal, follow events only — see §4).
- **`app/admin/messages/page.tsx`**: conversation list with debounced (300ms) participant search + flagged/hasReport/status filters, cursor "load more".
- **`app/admin/messages/[id]/page.tsx`**: thread view + two independent action surfaces (see BR-MESSAGING-020 for the full divergence):
  - **Direct Actions** sidebar (`warn`/`suspend_7`/`suspend_30`/`ban`), defaulting `targetUserId` to "the participant who is NOT the reporter of the most recent... " — actually defaults via `openDirectModal`'s own logic (not shown in excerpt but same shape as `openResolveModal`'s "the participant who isn't the reporter"). `warn` silently no-ops (no API call) if no open report exists for the conversation, yet still shows a success toast — **confirmed bug**, BRI-559. `suspend`/`ban` call `adminApi.banUserFromChat` directly, dropping the `lockConversation` checkbox value entirely (never sent to that endpoint) — **confirmed bug**, BRI-562.
  - **Reports** section inline resolve modal — calls `adminApi.resolveReport` properly, including `lockConversation` (honored only for the `ban` action server-side, per BR-MESSAGING-021).
  - Success toast reads "Action applied to {raw targetUserId}" — a long internal id, not a username — confirmed cosmetic bug, BRI-560.
- **`app/admin/messages/flagged/page.tsx`**: global flagged-message queue, reason filter, deep-links to the thread with `?highlight={messageId}` to scroll/highlight.
- **`app/admin/messages/reports/page.tsx`**: open-reports queue, resolve modal defaults `targetUserId` to "whichever of buyer/seller is NOT the reporter" (`conv.buyer.id === report.reporterId ? conv.seller.id : conv.buyer.id`) by fetching the conversation first.
- **Seller portal** (`apps/web/src/app/seller/messages/`) exists per `apps/web/CLAUDE.md`'s routing table but was outside this task's explicit scope (admin-only); not traced here.

---

## 7. Cross-cutting notes for test design

- **Guard matrix**: buyer/seller controller = `JwtAuthGuard` only (class). Admin controller = `JwtAuthGuard` + `RolesGuard` + `@Roles('ADMIN')` (class). The seller-initiated-conversation route additionally stacks `RolesGuard` + `@Roles('SELLER')` at the method level on an otherwise JWT-only controller — the ONE method-level role guard in this module.
- **AllExceptionsFilter**: all custom error codes in this module (`CHAT_BANNED`, `CONVERSATION_LOCKED`, `RECIPIENT_BLOCKED`, `BLOCKED_BY_ME`, `OFF_PLATFORM_PAYMENT`, `CONTACT_BLOCKED`) are thrown as `new HttpException({code, message, ...}, HttpStatus.FORBIDDEN)` — a plain object body, not a NestJS built-in exception class. Verify in a fresh test run that `AllExceptionsFilter` doesn't flatten/strip the `code`/`until` fields (the repo-root `messaging.md` notes "via patched AllExceptionsFilter" for exactly this reason — confirm the patch still exists before assuming the shape).
- **Two parallel moderation queues, one underlying ban mechanism**: `ConversationReport` (user reports) and flagged `Message` rows (auto-filter) are separate models reachable via separate admin routes, but BOTH ultimately gate the same two user fields (`chatBanUntil`, `chatWarningCount`) and the same `ConversationStatus.admin_locked` enum value — a test suite should exercise both queues independently AND verify they don't cross-contaminate (resolving a report must not touch flagged-message state and vice versa).
- **Gateway tests require real socket.io-client**, not just HTTP mocking — `test/messaging.gateway.e2e-spec.ts` (per repo-root `messaging.md`) is the existing reference for a full connect/focus/emit/disconnect cycle against a real server instance.
