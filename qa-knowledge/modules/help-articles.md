# Module: Help Articles

2 endpoints, `apps/api/src/help-articles/` (`help-articles.controller.ts`, `intercom-help-center.service.ts`, `dto/`). No Prisma model — **zero persistence**, every response is fetched live from Intercom's Articles API on each request. Tests: `help-articles.controller.spec.ts` (delegation + a real-Nest-app `ParseEnumPipe` 400 test via supertest), `intercom-help-center.service.spec.ts` (10 cases covering collection mapping, the shipping-topic search special-case, published-only filtering, and every failure mode).

Analyzed against commit `91e0447b` (see `overview.md`). Evidence: code, `docs/features/help-center-intercom-articles.md` (the authoritative feature spec, shipped 2026-09-30), Linear `BRI-338` (parent ticket, still **status: QA Testing**, not Done — note this for evidence classification below), `BRI-232` (epic), `BRI-339`/`BRI-380` (adjacent, explicitly out of this module's scope), mobile `services/helpArticlesApi.ts` + `store/helpArticlesStore.ts` + `screens/profile/HelpArticles.tsx` + `HelpSupport.tsx`.

## 1. `GET /help-articles/topics/:topic` (`help-articles.controller.ts:17-23`)

- **Auth**: none. Public, no guard — deliberate (comment in source: "same convention as `ShippingController`'s fee-schedule endpoint... Help Center content isn't user-specific or sensitive"). The mobile screen that calls it only ever mounts while signed in (`ProfileStack` is kept out of the guest tab tree per BRI-339's navigator gating), but that is a **frontend-only restriction** — nothing server-side would stop an anonymous caller.
- **Path param**: `topic`, validated by Nest's built-in `ParseEnumPipe(HelpTopic)` directly in the method signature (not a DTO) — `HelpTopic = 'buying' | 'selling' | 'returns' | 'shipping'`. Any other value → **400**, confirmed by `help-articles.controller.spec.ts`'s real-app supertest case, before the controller method body ever runs.
- **Business logic** (`IntercomHelpCenterService.getTopicArticles`): 
  - For `shipping`: **not a collection lookup at all** — delegates straight to `search('shipping')` (the keyword-search method, see endpoint 2). This is because the real Intercom workspace has no dedicated "Shipping" collection — several shipping articles (Order tracking, Shipping Rates, Shipping issues) sit outside any collection, so a collection-based lookup would miss them. Confirmed by a hardcoded code comment stating this was resolved by inspecting the real workspace, not guessed, and matched by its own test (`getTopicArticles for "shipping" runs a keyword search instead of a collection lookup`).
  - For `buying`/`selling`/`returns`: filters the full article list to `parent_id` ∈ a hardcoded `TOPIC_COLLECTION_IDS` map of real Intercom collection IDs (resolved 2026-09-30 against the live workspace). **`selling` aggregates 4 IDs** (the Selling collection plus its Payments/Listing/Shipping-and-Delivery sub-collections) because Intercom's own content hierarchy splits selling articles across sub-collections — a single-ID lookup would silently omit most of what a seller expects on that tile.
  - **Published-only filter is unconditional and server-side** (`fetchPublishedArticles` filters `state === 'published'` before any topic/search logic runs) — a draft article can never reach the mobile client regardless of topic or query. This is an explicit BRI-338 QA acceptance criterion, confirmed in both the source comment and the feature doc.
- **External dependency**: Intercom's `GET /articles?per_page=150` (real Articles API, `https://api.intercom.io`), Bearer-token auth via `INTERCOM_ACCESS_TOKEN` (ConfigService, optional/lazy env var — not in the boot-required list, same convention as `SHIPPO_API_TOKEN`). 10-second `AbortSignal.timeout`. The **entire article corpus is fetched on every single request** (no server-side caching) — `per_page=150` covers the workspace's current ~90 articles (34 published / 55 draft per the feature doc's dev-time smoke test) in one page; if the corpus ever exceeds 150, the service only fetches page 1 and logs a warning (`total_pages > 1`) rather than paginating further or throwing — **a real, documented truncation risk, not a hard failure**, worth a boundary test if/when the workspace grows past ~150 articles.
- **Response**: `HelpArticleSummaryDto[]` — `{ id, title, url }` only. No article body/HTML ever leaves the API; the client opens `url` (a real `help.redspur.com` link) in the existing `WebPage` WebView screen.
- **Error handling**: `INTERCOM_ACCESS_TOKEN` not configured → `InternalServerErrorException` (logged at `warn`). Non-2xx from Intercom → `InternalServerErrorException` (logged at `error`, includes the status). Network/timeout failure → `InternalServerErrorException` (logged at `error`, includes the underlying message). All three collapse to the same 500 status/generic message at the HTTP layer — a tester cannot distinguish "not configured" from "Intercom is down" from the response alone, only from server logs.
- **No pagination, filtering, or sorting params accepted** — the endpoint returns Intercom's full matching set for the topic, in whatever order Intercom's own `data` array returns it.

## 2. `GET /help-articles/search` (`:25-30`)

- **Auth**: none (same as above).
- **Query param**: `SearchHelpArticlesDto` — `q: string`, `@IsNotEmpty() @IsString() @MaxLength(200)`. Required — omitting `q` or sending `q=` (empty after whitelist/transform) fails DTO validation (400) **before** the handler runs. Note the distinct empty-string short-circuit INSIDE the service (`search()`'s `if (!needle) return []`) is dead code for the HTTP path specifically because the DTO's `@IsNotEmpty` already rejects an empty query at the validation-pipe layer — that in-service check only matters if the service is called directly (e.g. from a future consumer, or a unit test) bypassing the DTO.
- **Matching**: case-insensitive substring match against `title` OR stripped-HTML `body` (`stripHtml` is a naive `<[^>]+>` regex strip, not a real HTML parser — could leave stray entities/whitespace in edge cases, not tested against malformed HTML). **No relevance ranking** — the feature doc explicitly scopes this out ("search is a simple case-insensitive title/body substring match... will surface some loosely-related results for common words"). Same published-only filter and same "fetch full corpus every call" shape as endpoint 1.
- **Response/errors**: identical shape and failure modes to endpoint 1.

## Guard-application audit

Both routes have **zero guard decorators** at class or method level — confirmed by reading the controller file directly, not inferred from the "Public" comment. This is consistent with the feature's own design intent (non-sensitive, non-user-specific content) and the DTO's validation is the only input gate on either route.

## Frontend usage

### Mobile (only consumer found)

- `apps/mobile/src/services/helpArticlesApi.ts` — thin `request()` wrapper, one function per endpoint, URL-encodes the search query.
- `apps/mobile/src/store/helpArticlesStore.ts` — 15-minute TTL cache, independently keyed per topic and per search query (confirmed by the feature doc; store file itself not read endpoint-by-endpoint since it adds no server-contract information beyond caching).
- `apps/mobile/src/screens/profile/HelpArticles.tsx` — single screen for both topic-browse and live-search (BRI-338 design decision to avoid two near-duplicate list screens). On a failed re-fetch, falls back to **stale cached data** rather than showing a blank error screen (an explicit BRI-338 offline acceptance criterion) — only shows a genuine `error`/`offline` state if there is no cache to fall back to.
- `apps/mobile/src/screens/profile/HelpSupport.tsx` — the Help & Support screen's 4 Common Topic rows (Buying, Selling, Shipping & tracking, Returns & refunds) and search bar navigate into `HelpArticles`. Two adjacent rows on the same screen ("Ratings & reviews", "Terms of use & privacy policy") are **explicitly out of scope** for this module (Terms is `BRI-380`, now **Canceled** per Linear; Ratings has no ticket) and remain on a "Coming soon" fallback — not a gap in this module's own analysis, a deliberate scope boundary. "Contact support" on the same screen is `BRI-339`'s separate Intercom Messenger widget, not this module.
- Tapping a result navigates to the existing root-level `WebPage` screen with the article's real `help.redspur.com` URL — no in-app rendering of Intercom content.

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` — confirmed by grep, not assumed. The admin/seller portal has no Help Center surface.

## Business-rule-relevant findings for consolidation

- Published-only enforcement is server-side and unconditional (strong — can't be bypassed by topic/query).
- Shipping topic is a search special-case, not a collection lookup — a real, intentional asymmetry, not a bug, but worth its own test case so a future refactor doesn't "fix" it into a collection lookup and silently drop the shipping articles that live outside any collection.
- 150-article page-1-only fetch is a real scaling edge: not broken today, but no pagination exists if the corpus grows — flag as a dependency-map/gaps item, not a business rule violation.
- All three external-failure modes (missing token / Intercom non-2xx / network failure) are indistinguishable from the HTTP response alone (all 500) — a test scenario can verify the status code but not which internal cause produced it without log access.
- Evidence classification nuance: this feature is **implemented in code and the feature doc says "Shipped: 2026-09-30,"** but Linear's own `BRI-338` ticket status is **"QA Testing," not "Done"** as of this analysis — treat as implemented-and-code-verified, but not yet formally closed per the tracker. Don't conflate "shipped per the feature doc" with "closed per Linear" when citing evidence type.
