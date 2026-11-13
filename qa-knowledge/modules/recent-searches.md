# Module: Recent Searches

3 endpoints, `apps/api/src/recent-searches/` (`recent-searches.controller.ts`, `recent-searches.service.ts`, `recent-searches.repository.ts`, `dto/record-recent-search.dto.ts`). Backed by the `RecentSearch` Prisma model, added via `2026-08-27-add-recent-search-history.sql` (`apps/api/prisma/manual-sql/`, cited in `overview.md`'s architecture notes). By far the smallest and simplest module analyzed so far — no cross-module dependencies, no external services.

Analyzed against commit `91e0447b`. Evidence: `BRI-224` (empty-for-new-account), `BRI-427` (type-coercion validation gap, fixed).

## Guard

`@UseGuards(JwtAuthGuard)` at class level, `@Controller('me/recent-searches')` prefix — all three routes require authentication, no public access.

## 1. `GET /me/recent-searches` (`:19-22`) — `list`

- Returns up to `MAX_RECENT_SEARCHES` (= **10**, a hardcoded constant, not env-configurable) terms, newest-first, already capped and de-duplicated server-side. For a brand-new account with no search history, returns `[]` — explicitly tested and cited as `BRI-224`'s acceptance criterion ("is empty for an account that has never searched").
- **No query params** — no pagination, since the result set is hard-capped at 10 by the storage model itself (see endpoint 2).

## 2. `POST /me/recent-searches` (`:24-30`) — `record`

- **Body**: `RecordRecentSearchDto` — `term: string`, `@MinLength(1) @MaxLength(120)`. **`BRI-427` fix, confirmed by its own dedicated DTO spec**: a non-string `term` (number, boolean, null, array, object) is now rejected with a message that explicitly names the type problem ("term must be a string") rather than the class-validator default's confusing fallback (the bug this fixed: a numeric `term` used to produce an incidental "must be shorter than or equal to 120 characters" message instead of naming the actual type mismatch, and — per the fix's own description — a reporter's Postman run against an older deploy showed the numeric value silently coerced to a string and persisted; current code rejects it outright at the DTO boundary instead).
- **Business logic** (`RecentSearchesService.record`, read in full):
  1. Trims the raw term. **A blank/whitespace-only term after trimming is a silent no-op, not a 400** — the service's own comment is explicit about why: "the client already ignores empty submits and a 400 here would turn a harmless race into a visible failure on a screen that isn't about us." This means a test sending `{ term: "   " }` should expect `200` with the current (unchanged) list returned, not a validation error — a real, deliberate asymmetry worth its own test case, since it's easy to assume all blank-input handling in this codebase is DTO-rejected (it mostly is elsewhere, e.g. `saved-searches`' name field).
  2. **Upsert keyed on the lowercased, normalized term** (`termLower`, a unique composite key with `userId`) — recording "Wrangler" then "wrangler" updates the **same row** (moves it to the front, refreshes `searchedAt`) rather than creating two entries; the **casing displayed is whatever was typed most recently** (`term` column is overwritten on every upsert, even though `termLower` is the dedup key) — confirmed directly in the repository's own doc comment and the service spec's explicit assertion.
  3. **Prune to the newest 10** after every successful record (`pruneToMostRecent`) — queries the newest `MAX_RECENT_SEARCHES` ids, deletes everything else for that user. This runs on every single record call, not periodically — a user's row count for this table can never exceed 10 at any observable moment after a request completes.
  4. Returns the resulting list (`list(userId)`) so **the caller never has to guess the resulting order/dedup outcome** — deliberate API design per the service's own comment, confirmed by its own test ("returns the resulting list so the caller never re-derives the order").
- **No `GET`-then-`POST` race protection beyond the upsert's own atomicity** — not independently stress-tested in this pass; the unique constraint on `(userId, termLower)` is what Prisma's `upsert` relies on, so this should be safe under concurrent identical-term submissions by construction, but two *different* simultaneous terms racing the prune step were not traced for an edge case (e.g., could a prune triggered by request A delete a row request B just created, if B's upsert and A's prune interleave unfortunately? Not verified — flag as an unresolved concurrency question for `gaps-and-conflicts.md` rather than asserting either way).

## 3. `DELETE /me/recent-searches` (`:32-36`) — `clear`

- Deletes **every** recent-search row for the caller (`deleteAllForUser` — a `deleteMany` scoped strictly to `userId`, confirmed no cross-user leak risk by reading the Prisma call directly). Returns `{ success: true }`.

## Frontend usage

### Mobile (only consumer found)

- `apps/mobile/src/services/recentSearchesApi.ts` — 1:1 wrappers, explicitly documented in its own file header as "Server-side so they survive a logout — they're personal account data, like saved searches, not analytics," and "Every endpoint is token-only: a guest has no history to read or write, which is what keeps a brand-new account starting empty (BRI-224)." Both claims are confirmed by the server-side guard (class-level `JwtAuthGuard`, no optional/guest path) and the empty-for-new-account behavior above.

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` — confirmed by grep.

## Business-rule-relevant findings for consolidation

- **BR-RECENT-SEARCHES-001**: hard cap of 10 terms per user, enforced server-side on every write (not a display-only client trim) — the mobile client's own cap must agree with this or the list changes length on rehydration after logout, per the service's own code comment warning about exactly this mismatch risk.
- **BR-RECENT-SEARCHES-002**: a blank/whitespace term is a silent no-op (200, unchanged list), not a validation error — distinct from this module's own DTO's otherwise-strict type validation (`BRI-427`).
- **BR-RECENT-SEARCHES-003**: dedup is case-insensitive by storage key, but display casing always reflects the most-recently-typed variant.
- **Unresolved, flagged honestly**: whether a concurrent record-and-prune race across two near-simultaneous different-term submissions can ever drop a just-created row was not verified either way in this pass.
