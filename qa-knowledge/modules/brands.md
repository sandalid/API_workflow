# Module: Brands

1 endpoint, `apps/api/src/brands/` (`brands.controller.ts`, `brands.service.ts`, `brands.repository.ts`). Smallest controller in the entire API surface (one route).

Analyzed against commit `91e0447b`. Public read side of the taxonomy the `admin` module's `admin/taxonomy/brands` routes manage (separate batch, out of scope here).

## `GET /brands` (`brands.controller.ts:9-13`)

- **Auth**: none.
- **Business logic**: ordered alphabetically by `name` (the one taxonomy list in this batch that is **not** `sortOrder`-first — contrast with `categories`/`materials`, both of which order by `sortOrder` then `name`). This is a real, source-confirmed asymmetry: `brands.repository.ts`'s `findAll()` orders by `{ name: 'asc' }` only — no `sortOrder` column is read at all for this endpoint, even though the `Brand` model does carry a `navigationTab` boolean (used by a different, non-HTTP method, see below) and presumably a `sortOrder`-capable admin screen exists (`admin/taxonomy/brands` CRUD, separate module). Worth a direct cross-check against `admin.controller.ts`'s brand CRUD to confirm whether admin can even set a brand display order that this endpoint would then ignore — flagged for the `admin` batch to confirm, not asserted here as a defect.
- **`itemCount` is computed per-request**, not stored: a Prisma `_count` aggregate over each brand's `listings` relation, scoped by `LIVE_LISTING_WHERE` (the shared "soft-deleted + live status" filter constant used across the listings module) — so a brand's item count only reflects currently-live, non-deleted listings, not every listing ever filed under it. No caching observed on this count; every call to `GET /brands` re-aggregates across the full `Listing` table filtered by brand — a potential hot-path cost worth a load-shape test as the listings table grows, though not a correctness issue.
- **Response**: `BrandWithItemCount[]` — every `Brand` column plus the computed `itemCount`.

## Internal (non-HTTP) method worth noting

- `findNavigationTabBrands()` — brands flagged `navigationTab: true` (the small curated subset meant to appear as top-level nav tiles, per the `navigationTab` field seeded in `seed.service.ts`'s `BRANDS` constant — see `modules/seed.md`). Not exposed via its own route; presumably consumed by a screen that needs only the curated subset rather than filtering the full `GET /brands` response client-side (not verified which screen — see Frontend usage below, mobile only calls the one public route).

## Frontend usage

### Mobile

- `apps/mobile/src/services/brandsApi.ts` — calls `GET /brands` only; maps the response down to `{ id, name, itemCount }` (drops `slug`/`logo` client-side — `logo` is accepted by the DTO-level response but never used by this consumer, a DTO-accepted-vs-actually-used gap worth noting). `getBrandById` is a **client-side filter over the full list**, not a dedicated API call — the module's own code comment notes this explicitly: "The API currently exposes only `GET /brands`, so this filters client-side." No `GET /brands/:id` route exists — confirmed, this module has exactly one route.

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` to the public `GET /brands` route — admin manages brands entirely through `admin/taxonomy/brands` (separate module).

## Business-rule-relevant findings for consolidation

- **BR-BRANDS-001**: `GET /brands` orders alphabetically by name, not by any admin-settable display order — a real asymmetry with `categories`/`materials` in the same discovery-taxonomy group, worth its own explicit test assertion so a future "fix" that aligns the ordering doesn't silently change behavior an existing screen may depend on (or vice versa, if the asymmetry is itself the bug).
- **BR-BRANDS-002**: `itemCount` reflects only live, non-deleted listings at request time (via `LIVE_LISTING_WHERE`), computed fresh on every call — not a stored/cached counter.
