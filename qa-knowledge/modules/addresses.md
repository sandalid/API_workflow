# Module: Addresses

7 endpoints across two controllers — `addresses.controller.ts` (`@Controller('me/addresses')`, 5 routes, JWT-guarded) and `us-places.controller.ts` (`@Controller('addresses/us')`, 2 routes, **public, no guard**). Backed by the `Address` Prisma model plus a bundled US ZIP/city/state reference dataset (`common/utils/us-address.util.ts`, not itself exposed as a model — static data shipped with the API).

Analyzed against commit `91e0447b`. This module directly resolves a question this knowledge base's own earlier analysis had left open: **the ZIP↔city↔state consistency check is real, is enforced server-side, and is not merely a client-side mirror** (contrast with several other mobile state-mirroring utils documented in `overview.md` that genuinely are client-only conveniences). Evidence: `BRI-263` (original + "reopened" fix), `BRI-309` (City/State picker requirement), `BRI-807` (accepted-cities list), `BRI-482`/`BRI-392`/`BRI-312` (not read individually this pass, present in `docs/fix/addresses/`).

## `me/addresses` routes (JWT-guarded, `@UseGuards(JwtAuthGuard)` at class level)

### 1. `GET /me/addresses` (`:22-26`)

- Lists all of the caller's addresses, ordered `isDefault desc, createdAt desc` — the default address, if any, always sorts first.

### 2. `GET /me/addresses/zip-lookup` (`:28-36`) — **declared before `:id` routes on purpose**, confirmed by the controller's own doc string ("Declared before the `:id` routes so the exact path matches first"). Identical implementation and response shape to the public `addresses/us/zip-lookup` below (both call `AddressesService.lookupZip` directly) — kept as a separate authenticated route "for older app builds" per the public route's own doc comment, i.e. a deliberate temporary duplication during a migration to the public route, not an oversight.

### 3. `POST /me/addresses` (`:38-45`) — `create`

- **Body**: `CreateAddressDto` — `label` (optional, `home`|`work`), `name`/`street` (required), `apt` (optional), `city`/`state`/`zip` (required), `country` (optional, defaults `'US'`), `isDefault` (optional boolean).
- **`state` must be a real USPS state/territory abbreviation** (`@IsIn(US_STATE_CODES)`) — this closed a real gap: `BRI-263`'s original bug was the API accepting *any* string for `state` and *any* digit-string for `zip`, so a bad mobile-side value like `"WW"`/`"10300"` persisted with zero server-side pushback.
- **`zip` must match a 5-digit-or-ZIP+4 shape** (`@Matches`) — format-only, not a real-ZIP-exists check (the test suite explicitly notes an unrecognized-but-well-formed ZIP like `00000` is accepted at this layer — the shape rule, not a coverage-database rule, is what's enforced here).
- **Class-level `@IsConsistentUsAddress()` decorator on the whole DTO** (`BRI-263` *reopened*): validates that `city`+`state`+`zip` all describe **the same real place**, not merely that each field is individually well-formed — the regression this specifically closes: `"New York, CA 10001"` passed every per-field rule (CA is real, 10001 is well-formed, New York is a real city) before this check existed. A mismatch produces a single error naming the conflicting fields; this is a genuinely non-trivial, combination-level validator, not a simple per-field rule.
- **Service-layer Shippo deliverability check** (`assertDeliverable`, on top of the DTO's own consistency check): calls `ShippoService.validateAddress` with the full address (apt mapped to Shippo's `street2` field) — **blocks the create with a 400 if Shippo actively reports the address undeliverable**, using Shippo's own message text when available. **Fails OPEN** (logs a warning, allows the save through unvalidated) if the Shippo call itself throws (token misconfigured, Shippo outage) — explicitly, deliberately, consistent with every other Shippo touchpoint in the codebase (checkout preview, ship-time rate quoting) per the service's own doc comment citing `docs/features/shippo-integration/shippo-reference.md § 7`. **This is a real, source-confirmed distinction a test suite must respect**: a Shippo outage does not block address creation (fail-open), but an address Shippo actively flags as undeliverable (Shippo reachable, answer is "no") does block it (hard-fail) — two different test scenarios with opposite expected outcomes depending on which Shippo failure mode is simulated.
- **Default-address exclusivity, transactional**: if `isDefault: true`, the repository wraps "demote every other address to non-default" + "create this one as default" in a single `$transaction` — no window where two addresses could both read as default.

### 4. `PATCH /me/addresses/:id` (`:47-55`) — `update`

- **Ownership**: 404 if the address doesn't exist, 403 (`ForbiddenException`, "Not your address") if it belongs to another user — cleanly distinguishable, same pattern as `saved-searches`.
- **Partial-edit consistency check, the subtler half of `BRI-263` reopened**: the DTO's own class-level `@IsConsistentUsAddress()` can only compare fields that were actually **sent** in this request — a ZIP-only edit carries no city/state in the payload to cross-check, so the DTO alone would wave it through even if it silently made the stored row internally inconsistent. The **service layer**, which already has the stored row loaded, **completes the triple from the existing address** before re-running the same consistency check (`usAddressConsistencyErrors`) — confirmed directly by reading `AddressesService.update` and its own explanatory comment. This is why: a ZIP-only edit that contradicts the *stored* state is rejected (test: editing to `10001` on a stored Austin-TX address throws naming "NY, not TX"), but a ZIP-only edit that still agrees with the stored city/state passes.
- **Shippo re-validation is conditional, not unconditional**: only re-runs `assertDeliverable` when an address-affecting field was actually sent (`name`/`street`/`apt`/`city`/`state`/`zip`/`country`) — toggling only `isDefault` makes **zero** Shippo calls, a deliberate cost-discipline decision cited to the same `docs/features/shippo-integration/shippo-reference.md § 7`. Confirmed by a dedicated test asserting no Shippo call for an `isDefault`-only edit. Same fail-open behavior as create when Shippo itself errors.
- Same transactional default-promotion behavior as create, scoped to exclude the address being updated from the demotion.

### 5. `DELETE /me/addresses/:id` (`:57-65`) — `delete`

- Same ownership check (404/403). Hard delete, `204 No Content` on success. **No automatic promotion of another address to default after deleting the current default** was found in the repository's `delete()` method (a plain `prisma.address.delete`, no follow-up update) — if this is a real gap (a user left with zero default address after deleting their only/default one), flag it in `gaps-and-conflicts.md` rather than assuming an app-level fallback exists; not independently verified whether any consumer (e.g. checkout) tolerates a user with addresses but no default.

## `addresses/us` routes (public, **no guard** — confirmed directly via the controller's own spec asserting `Reflect.getMetadata(GUARDS_METADATA, ...)` is `undefined`)

### 6. `GET /addresses/us/cities` (`:20-27` of `us-places.controller.ts`)

- **Query**: `UsCitiesQueryDto` — `state`, transformed to trimmed-uppercase, `@IsIn(US_STATE_CODES)`. Returns `{ state, cities }`, A–Z sorted, de-duplicated, from the bundled dataset.
- **Deliberately public**: the controller's own doc comment states seller onboarding collects a ship-from address **before an account necessarily exists**, so a session-gated route would block that flow. Cache-Control set to `public, max-age=86400` (24h) — the dataset only changes when the bundled data itself does, so the app is explicitly permitted to cache this for a full day.
- Rate-limited only by the repo-wide global throttler (100 req/min/IP) — no stricter tier, consistent with this being non-sensitive reference data.

### 7. `GET /addresses/us/zip-lookup` (`:29-36`)

- Identical to the authenticated `/me/addresses/zip-lookup` twin — same underlying `AddressesService.lookupZip` call. Returns `{ zip, city, state, acceptedCities }`. **404 (not an empty 200 body) for an unrecognized ZIP** — deliberate, so the client can leave the user's typed fields alone rather than blanking them on a lookup miss.
- **`acceptedCities` is the real mechanism behind `BRI-309`'s City/State picker requirement and `BRI-807`'s "accepted cities" concept**: for a borough-style ZIP (the test fixtures use Queens/Jamaica, NY `11432`), `acceptedCities` lists multiple valid names (`['Jamaica', 'New York', 'Queens']`) — `city` is the one value the form auto-fills, but a save is accepted for **any** name in `acceptedCities`, not just the auto-filled one. This is the concrete mechanism `apps/mobile/CLAUDE.md`'s `utils/address.ts`'s `addressMismatch` is described as mirroring — and this analysis confirms that mirror has a real, matching server-side source of truth (the same `lookupZip`/`usZipAcceptedCities` function the save-time consistency check itself effectively encodes via `IsConsistentUsAddress`), not an independent guess.

## Frontend usage

### Mobile

- `apps/mobile/src/services/placesApi.ts` — calls only `GET /addresses/us/cities` (the public route). Its own doc comment states explicitly: *"The app carries no copy of its own... Public route: seller onboarding can run before a session exists"* — directly matching the server-side design intent.
- Zip-lookup and address CRUD are presumably called from `apps/mobile/src/screens/checkout/AddressEntry.tsx`/profile address-management screens and a dedicated `addressesApi`-style service — not independently located/read by filename in this pass (no `addressesApi.ts` appeared in the earlier full service-file listing; the CRUD calls may live inline in `checkoutApi.ts` or a differently-named file — flag as a specific follow-up for consolidation rather than asserting a particular file).
- `apps/mobile/src/utils/address.ts`'s `addressMismatch` (cited in `apps/mobile/CLAUDE.md`, not re-read in this pass) is the client-side mirror of the server consistency check documented above.

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` to any of these 7 routes — confirmed by targeted grep (zero matches for the literal route strings). Earlier broad matches on the word "address" in web files were order/shipping-address **display** (data already embedded in order/seller API responses from other modules), not calls into this module's endpoints.

## Business-rule-relevant findings for consolidation

- **BR-ADDRESSES-001**: city/state/ZIP combination is validated server-side as a real place, both on create (whole-DTO check) and on partial update (service completes the triple from the stored row first) — this is enforced, not merely mirrored client-side. Correction to the earlier working hypothesis in this knowledge base's planning notes, which had flagged this as an open question.
- **BR-ADDRESSES-002**: Shippo deliverability check fails OPEN on Shippo outage/misconfiguration, fails CLOSED (blocks the save) when Shippo is reachable and actively reports non-deliverable — two distinct, oppositely-resolving test scenarios.
- **BR-ADDRESSES-003**: default-address promotion is transactional on both create and update; **no automatic re-promotion was found on delete** of the current default — flag as a gap pending confirmation against checkout's tolerance for a no-default state.
- **BR-ADDRESSES-004**: the public `addresses/us/*` routes exist specifically to support pre-session flows (seller onboarding ship-from address) and are safely, intentionally cacheable for 24h.
