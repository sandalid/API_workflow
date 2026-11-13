# Module: events

1 endpoint. `@Controller('events')` with class-level `@UseGuards(JwtAuthGuard)` (`apps/api/src/events/events.controller.ts:9`).

```
POST /events    events.controller.ts:19-29
```

## Purpose

**Behaviour-capture for a personalised home feed, write-only in this phase** — the module doc comment on `EventsModule` states it plainly (`events.module.ts:6-15`): *"Write-only in this phase — nothing reads `ListingEvent` yet. Capture ships first and alone so history is accumulating by the time scoring is switched on."* This is BRI-50 phase 1; nothing in `apps/api/src` currently queries `ListingEvent` for ranking — confirmed by the schema comment on the sibling `model` at `schema.prisma:2195-2201` ("phase 2") and by there being no scoring/read service in the `events` module's exports.

**Not a general analytics/telemetry endpoint** — it only accepts listing-interaction events (`view`, `dwell`, `save`, `unsave`, `offer`, `purchase`, `share` — `ListingEventType`, `schema.prisma:2144-2159`), typed and bounded by DTO, not an arbitrary event-name/payload sink. There is a separate, unrelated Mixpanel-based analytics track referenced in Linear (BRI-93/BRI-344, "event-analytics tool," client-SDK-side) that this endpoint has nothing to do with — don't conflate the two when searching Linear for "analytics."

## Auth model — authenticated only, no guest path

`@UseGuards(JwtAuthGuard)` at the class level means **every request needs a valid bearer token; there is no guest/anonymous ingestion today**, despite the task brief's hypothesis that this "likely needs to work for both signed-in and guest." The controller's own doc comment confirms this is a deliberate, scoped-down decision rather than an oversight (`events.controller.ts:13-18`): *"Authenticated only, so guest browsing is not recorded. That is deliberate for now: a guest has no home feed to personalise (BRI-71/BRI-147), so guest events would have no reader. The nullable `userId` column leaves room to add device-scoped capture later without a migration."* `ListingEvent.userId` is indeed nullable in the schema (`schema.prisma:2167`) specifically to leave this door open. Mobile's own queue (`listingEventsStore.ts:86-88`) mirrors this: `flush()` no-ops if there's no token, so a guest's interactions are captured locally (bounded to 200 queued events, `QUEUE_CAP`) but never sent, and are lost on sign-out (`reset()`) or app kill.

## Synchronous, not queued

The whole batch is processed **in-request**: `EventsService.record` (`events.service.ts:47-96`) does one `findListingFacets` read, builds all rows in memory, then one `repo.createMany` write (`prisma.listingEvent.createMany`) — no BullMQ/queue module involvement, no deferred job. The response (`RecordEventsResult`) is returned synchronously once the INSERT completes. There is no retry/backoff on the server side; resilience is entirely client-side (see below).

## Request/response shape

- **`202 Accepted`, not `201 Created`** (`@HttpCode(HttpStatus.ACCEPTED)`, `events.controller.ts:23`) — deliberate per the controller's comment (`:20-22`): *"the batch is accepted for recording, but events referencing a deleted listing — or a seller's own listing — are dropped by design, so 'Created' would overpromise."*
- **`RecordEventsDto`** (`dto/record-events.dto.ts`): `events: ListingEventInputDto[]`, `@ArrayMinSize(1)`, `@ArrayMaxSize(MAX_EVENTS_PER_BATCH = 50)`. Each item: `listingId` (`@IsString @MinLength(1) @MaxLength(60)`), `type` (`@IsIn(EVENT_TYPES)` against the live `ListingEventType` enum values), `dwellMs` (optional, `@Type(() => Number) @IsInt @Min(0)`, meaningful only for `type: 'dwell'`).
- **No client-supplied timestamp** — deliberate, documented at the DTO (`:43-47`): a client timestamp would let a caller backdate events into whichever scoring window suited them; the server clock (`createdAt: @default(now())`) is the only one that counts. Cost: an offline-queued event is attributed to flush time, not real occurrence time.
- **Response** (`RecordEventsResult`, `events.service.ts:11-18`): `{ accepted, skipped, reasons: { unknownListing, ownListing, tooShort } }` — a per-batch outcome summary, not a per-event echo. A client cannot tell *which* of its submitted events landed vs. were dropped, only the aggregate counts and reason buckets.

## Screening logic (`EventsService.screen`, `events.service.ts:106-127`)

Applied per-event, after one batched `findListingFacets` lookup (`events.repository.ts:26-31`, one query for the whole batch regardless of size — explicitly not routed through `ListingsService.findById`, which would be 50 heavy reads for two columns, per the repository's own comment `:17-24`):

1. **`unknownListing`** — the listing doesn't exist in the facets map (deleted mid-session, or a bad id). Caught before the FK would reject it, so one stale id doesn't fail the whole `createMany`.
2. **`ownListing`** — `listing.sellerId === userId`. A seller interacting with their own listing is dropped outright, not stored-and-filtered-at-read-time, because (per the comment `:111-116`) the row would have no legitimate reader — not ranking, and not seller-analytics either (a seller's own visits would distort their own view count). This is the explicit anti-wash-trading guard called out by BRI-50 state 5.
3. **`tooShort`** — `dwell`-type only, `dwellMs < DWELL_MIN_MS (1,000ms)`. Below the floor is treated as a mis-tap/instant back-swipe and dropped, not stored as a near-zero duration.
4. **Non-`dwell` events never carry a duration** — even if the client sends `dwellMs` alongside a `save`/`view`/etc., it's discarded (`screen()` returns `{ verdict: 'keep' }` with no `dwellMs` for any non-dwell type, `:119`), so the column means exactly one thing.
5. **Dwell ceiling** — `dwellMs` is clamped to `DWELL_MAX_MS` (120,000ms / 2 minutes) rather than dropped; the server re-applies both bounds even though the client already clamps, because (per comment `:100-104`) the server cannot assume the client is the current build.
6. **Category is denormalised at write time** (`categoryId: listing.categoryId`, `events.service.ts:82`) from the listing facets, specifically to keep the hot category-affinity scoring query off a join with `Listing` later (schema comment, `schema.prisma:2172-2176`) — also means a `ListingEvent` row survives a category's own deletion, since it's not a relation.
7. **No per-event error surfaced** — a batch with some bad events never throws; the service's own doc comment (`:39-45`) states this is because the client clears its local queue on any 2xx, so failing the whole batch over one bad event would strand every other event and have the client retry the same doomed payload forever.

## Frontend usage (mobile)

- **`apps/mobile/src/services/eventsApi.ts`** — one call, `eventsApi.record(events, token)` → `POST /events`.
- **`apps/mobile/src/store/listingEventsStore.ts`** — the actual queue. In-memory only (lost on hard app kill, by design — "the signal is statistical and no single view matters," `:53-54`), capped at `QUEUE_CAP = 200`. `addDwell` accumulates multiple look-away/return spans into one pending dwell entry per listing rather than recording shallow repeated visits. `flush(token)`:
  - No-ops if already sending, queue empty, or no token (guest/signed-out).
  - **Client-side pre-filters sub-floor dwells before sending** (`:92-93`) — wasted round trips for events the server would drop anyway are avoided, not merely tolerated.
  - Takes the batch out of the **live** queue (not a snapshot) before the request, so an event captured mid-flight survives and a still-accumulating dwell starts a fresh entry rather than double-counting.
  - **No retry loop on failure** — a failed flush puts the batch back on the front of the queue for the *next natural flush* (app background, sign-out, next full-batch threshold), explicitly not hammered, because (per comment `:116-118`) this is telemetry and retrying costs the buyer battery for no benefit.
- **`apps/mobile/src/hooks/useDwellTracking.ts`** — focus-based (not mount-based) timing via `useFocusEffect` + `AppState`, so a listing screen buried under a checkout stack doesn't keep accumulating, and backgrounding the app doesn't let dwell run overnight. Flushes opportunistically on backgrounding and on unmount once a full batch (`MAX_EVENTS_PER_BATCH`) has built up.
- **Call sites confirmed for all 7 `ListingEventType` values** (`grep` across `apps/mobile/src`): `view`/`dwell` — `ProductDetail.tsx:249` / `useDwellTracking.ts`; `save`/`unsave` — `likesStore.ts:53`; `offer` — `offersStore.ts:89`; `share` — `screens/modals/ShareSheet.tsx:133`; `purchase` — `cartStore.ts:298-301` (one event per **distinct** listing in the order, not per unit — quantity is already on the order, and the comment is explicit that counting a 3-unit purchase as three signals would let basket size masquerade as popularity).

## Business rules

See `qa-knowledge/fragments/notifications-support.business-rules.json` for the structured `BR-EVENTS-*` list (auth model, screening order, dwell bounds, batch cap, denormalisation).

## Notes / scope boundaries

- This module has **no Linear tickets of its own found by direct keyword search** ("event tracking", "analytics event") beyond BRI-50 (the parent epic referenced throughout the source comments but not independently re-queried here, since the task scope is this module's read/delete-equivalent mechanics, not the scoring feature it feeds) and the unrelated BRI-93/BRI-344 Mixpanel-SDK tickets, which concern a client-side analytics SDK, not this server endpoint. Treat "no ticket found" as "none found by this search" per the standing limitation in `qa-knowledge/overview.md`.
- No web admin usage found (`grep -i "events" apps/web/src` turned up nothing related to listing-interaction events; the admin layout's only "Notifications" string is an unrelated "coming soon" placeholder label, not a feed of these events).
