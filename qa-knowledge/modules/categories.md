# Module: Categories

3 endpoints, `apps/api/src/categories/` (`categories.controller.ts`, `categories.service.ts`, `categories.repository.ts`, no DTOs — all three routes take no input). No dedicated spec file for the controller was found in this read pass (not confirmed absent beyond this module's own directory listing — flagged as a gap, not asserted as a fact).

Analyzed against commit `91e0447b`. This module is also the **public read side** of the taxonomy the `admin` module's `admin/taxonomy/*` routes manage — `admin.controller.ts`'s taxonomy CRUD is out of this module's scope (separate batch) but every endpoint here reads the same `Category`/`Subcategory`/`Type`/`FilterAttribute` tables admin writes to.

## 1. `GET /categories` (`categories.controller.ts:10-14`)

- **Auth**: none — no guard on any route in this controller.
- **Business logic**: flat list, ordered `sortOrder asc, name asc` — **never** plain alphabetical. The repository's own doc comment states this is deliberate: admin sets a non-alphabetical display order (Women, Men, Kids, Gear per `BRI-356`) and the mobile category strip must respect it; sorting by name here would silently discard that admin choice. Confirmed directly in `findAll()`'s `orderBy`.
- **Response**: raw `Category[]` (id, name, slug, icon, image, sortOrder, timestamps) — unfiltered, no DTO shaping at the controller/service boundary (contrast with `getTree()`/`getFilterAttributes()` below, which do map explicitly).

## 2. `GET /categories/tree` (`:17-21`)

- **Auth**: none.
- **Route-order note** (explicit in the source comment): declared *before* any future `:id`-style route would need to be, to avoid a literal `tree` segment being swallowed by a parameter route — currently moot since no `:id` route exists on this controller, but documents the author's intent for future routes.
- **Business logic**: the full Category → Subcategory → Type 3-level tree, each level ordered `sortOrder asc, name asc`. **Type-level `image` is deliberately excluded** from this response — a real, documented production constraint: taxonomy images are stored as base64 data URIs directly in the column (not via `/uploads`), the tree has 187 types, and a single 1.3MB type image was enough to push the response past the mobile client's 30-second timeout. Categories and subcategories (45 rows total) keep their images since those feed actual browse tiles; types have no tile today, so there's nothing to show. **A type's image must be fetched individually if ever needed — no endpoint for that was found in this module** (flag as a dependency-map gap if a future feature needs one). `docs/ops.md` is cited in-code as holding the real fix recommendation (route taxonomy images through `/uploads` like every other image) — not yet implemented.
- **Service-level mapping** (`CategoriesService.getTree`): explicitly re-maps every field rather than returning the Prisma result raw, specifically to keep `createdAt`/`updatedAt` (and any future column) from leaking into a public response by default — a deliberate allow-list pattern worth mirroring as the taxonomy model grows.

## 3. `GET /categories/filter-attributes` (`:24-28`)

- **Auth**: none.
- **Business logic**: every `FilterAttribute` with its `values` (ordered by `sortOrder`) and `targets`, but the response shape flattens `targets` into two separate id arrays (`subcategoryIds`, `typeIds`) rather than nesting attributes under the tree. Deliberate, per the service's own comment: the filter panel already knows which taxonomy node the shopper is browsing, so it needs an id-keyed lookup, not a second copy of the tree — nesting would duplicate each attribute once per node it targets.

## Internal (non-HTTP) methods worth noting for dependency-map / cross-module accuracy

Not endpoints, but exported and consumed elsewhere, so a tester tracing a listing-creation or visual-search flow will hit this module's code even though it has no route of its own here:
- `findAllForClassification()` — categories eligible for AI visual-search classification, env-configurable (`VISUAL_CLASSIFIER_CATEGORY_SLUGS`, default `women,men,kids,gear`). Consumed by the AI/visual-search module (out of this batch's scope).
- `findTypeForSubcategory` / `findSubcategoryForCategory` — parent/child relationship validators, almost certainly used by listing creation to verify a submitted type/subcategory pair is structurally valid (cross-reference `listings` module, not re-verified here).
- `findAllSubcategories` / `findSubcategoriesByCategoryId` — feed the category-affinity/visual-classification subsystems (`feed/category-affinity.service.ts`), not this module's own endpoints.

## Frontend usage

### Mobile

- `apps/mobile/src/services/categoriesApi.ts` — calls all three endpoints. Notable client-side resilience pattern (BRI-272): an **in-memory, session-lifetime cache** per endpoint (`cached`/`cachedTree`/`cachedAttributes`) serves the last successful response on a subsequent fetch failure, specifically so one dropped request doesn't paint a blank category strip on any of the ~10 screens that call `getCategories()` (Feed, SearchLanding, Filters, CategoryBrowse, ShopFor, PrefCategories, Sell flow, etc.) — each of those screens otherwise swallows a failure into an empty list with no error surfaced. The cache is **not persisted** (no AsyncStorage dependency installed app-wide) — a cold start with no connectivity still has nothing to show; this is a known, explicitly-noted-on-the-ticket limitation, not an oversight.
- `getTree()` is rendered in the **exact order received**, never re-sorted client-side — mirrors the server's own "respect admin order" rule (BRI-356).
- Icon mapping (`resolveIcon`) translates API-sent domain icon keys (e.g. `"boot"`) to real Ionicons glyph names, falling back to a generic tag icon for anything unrecognized — a DTO-accepted-vs-actually-used distinction worth a test case: the API can send any string in `icon`, but only a known key or a valid Ionicons name renders meaningfully; anything else silently renders the fallback glyph, never an error.
- `resetCache()` is NOT called on logout in this file (unlike `materialsApi`/others) — taxonomy is public and identical for every user, so there's no per-user staleness risk; included here only to confirm this is a deliberate omission, not an unverified gap.

### Web

`apps/web/src/app/admin/taxonomy/*` reads/writes taxonomy via `admin/taxonomy/*` (the admin module's own endpoints, separate batch) — **not** this module's public read routes. No reference to `GET /categories`, `/categories/tree`, or `/categories/filter-attributes` found in `apps/web/src/lib` or `apps/web/src/app` (confirmed by grep) — the admin portal manages and previews taxonomy entirely through its own write-capable admin endpoints, never the public read surface.

## Business-rule-relevant findings for consolidation

- **BR-CATEGORIES-001**: category/subcategory/type ordering is always `sortOrder` first, name second, across every one of this module's three endpoints and the internal methods — never pure alphabetical. Enforced identically at the repository query level in all cases (not inconsistent between endpoints).
- **BR-CATEGORIES-002**: type-level images are excluded from the bulk tree response specifically to avoid a documented client timeout (187 types × up-to-1.3MB base64 images). No endpoint exists to fetch a single type's image — flag in `gaps-and-conflicts.md` as a feature gap if ever needed, not a defect in what exists today.
- No endpoint in this module requires authentication — confirmed by reading the controller directly (no guard decorators anywhere), consistent with taxonomy being public, non-user-specific content.
