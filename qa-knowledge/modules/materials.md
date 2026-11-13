# Module: Materials

1 endpoint, `apps/api/src/materials/` (`materials.controller.ts`, `materials.service.ts`, `materials.repository.ts`). Newest of the taxonomy modules — built for `BRI-811` ("Admin Taxonomy — Manage Material options from the admin panel," Linear status **QA Testing** as of this analysis).

Analyzed against commit `91e0447b`.

## `GET /materials` (`materials.controller.ts:9-13`)

- **Auth**: none.
- **Why this module exists at all** (per `BRI-811`'s own description, read directly): before this ticket, the Material options a seller picks from when listing an item were **hardcoded in the mobile app** (`apps/mobile/src/mocks/facets.ts`'s `MATERIALS` constant) — changing them required a mobile code change and a new app build, and admin had no control. This endpoint is the read side of a new admin-managed `Material` table (name, slug, sort order), added via an additive migration per the ticket's own scope description — consistent with this repo's stated migration-safety conventions.
- **Business logic**: ordered `sortOrder asc, name asc` (same convention as `categories`, asymmetric with `brands` — see `brands.md`). Response select-shape is a strict allow-list (`MATERIAL_OPTION_SELECT` — `id`, `name`, `slug` only, via `satisfies Prisma.MaterialSelect`), so no stray column (e.g. `createdAt`, admin audit fields) can leak into the public response even if the `Material` model grows new columns later — a stronger-than-`categories`' pattern (there, the allow-list is applied manually in the service's `.map()`; here it's enforced at the Prisma `select` level, closer to the source).
- **`Listing.material` itself is free text, not a foreign key** — confirmed by the mobile client's own code comment ("`Listing.material` is free text"). This endpoint supplies a **suggested, admin-curated list of options**, not an enforced enum — a listing's actual stored material value is not validated against this list at write time (not independently re-verified against the listings module's DTO in this pass — flagged for cross-check against `modules/listings.md`, which is already written and should be spot-checked for this specific DTO constraint during consolidation).

## Frontend usage

### Mobile

- `apps/mobile/src/services/materialsApi.ts` — calls `GET /materials`, maps to a plain `string[]` of names (discards `id`/`slug` client-side, consistent with `Listing.material` being free text rather than an FK). Two layers of resilience, more defensive than `categoriesApi`'s single-layer cache:
  1. An in-memory `cached: string[] | null`, same last-good-answer shape as `categoriesApi` (explicitly cited as mirroring BRI-272 in its own comment).
  2. A **built-in fallback list** (`mocks/facets.ts`'s `MATERIALS` — the very constant this whole feature was built to stop being the source of truth) served when there is **neither** a successful server response **nor** a cache yet. This is deliberate per `BRI-789` (a real, confirmed-fixed production bug: "AI Snap-to-List Material field opens an empty sheet — no options to choose," root-caused to exactly this gap before the fallback was added) — the code comment states explicitly: *"Never empty (BRI-789: the Material sheet must never open blank)."*
  - Net effect: a server outage or empty admin-configured list degrades gracefully to the pre-BRI-811 hardcoded list, never to an empty picker — this is the one place in the discovery-taxonomy group where a client-side fallback is a deliberately-designed safety net rather than an incidental cache-miss behavior.
- `peek()` — synchronous, no-request accessor for the current cache, used wherever a caller needs a non-blocking "do we already have this" check (not traced to a specific screen in this pass).

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` to the public `GET /materials` route — admin manages the list via `admin/taxonomy/materials` (separate module, including the `PUT /admin/taxonomy/materials/order` reorder endpoint referenced in the inventory).

## Business-rule-relevant findings for consolidation

- **BR-MATERIALS-001**: `GET /materials` is a suggestion list, not an enum enforcement — `Listing.material` accepts free text independent of this endpoint's contents. A test asserting "a listing can only be created with a material from this list" would be testing a rule that does not exist in the code as read; confirm against `listings.md`/the listing-creation DTO before writing that scenario as an expected-pass case.
- **BR-MATERIALS-002**: this is the one taxonomy endpoint in the group with a real production-incident-driven client fallback (BRI-789) baked in — relevant for a test scenario specifically verifying the mobile Material picker is never empty, independent of server state.
- Ticket status nuance: `BRI-811` is "QA Testing" in Linear, not "Done" — implemented-in-code and functioning per this read, but not yet formally closed per the tracker.
