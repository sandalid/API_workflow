# Progress — QA Knowledge Base

## Scope decisions (confirmed with user, 2026-11-10)

1. Frontend scope: **mobile + web** both traced (not mobile-only).
2. Ticket source: **Linear MCP** (teams `REDB1`, `BRI`), queried per module.
3. Pacing: **full sweep now**, via parallel subagents grouped by module, writing into `qa-knowledge/` as they go.

## Foundational work (done by coordinator, not delegated)

- [x] Repo structure survey (backend 31 modules/37 controllers, mobile 562 files, web app router + lib).
- [x] `endpoint-inventory.json` generated programmatically from `@Controller`/`@Get|Post|Patch|Put|Delete` decorators across all 37 controller files — 288 routes, verified no duplicate IDs, spot-checked path construction for root-controller modules (`disputes`, `orders`, `reviews`, `messaging`, `saved-searches`).
- [x] `overview.md` — architecture facts (no global prefix, global pipes/filters, raw-body webhook routes, guards, Prisma schema location, mobile state-mirroring utils with known BRI-xxx drift bugs).
- [x] Linear teams identified: `REDB1` (active), `BRI` (frozen launch baseline).
- [x] Branch `docs/qa-knowledge-base` cut from `origin/development` (repo's `block-edits-on-main` hook requires this even for docs-only work).

## ✅ Continuation session 2026-11-10 — corrections + reconciliation done

Per explicit user instruction, before resuming missing-module work:

1. **Exact analyzed commit recorded**: `91e0447b86b27f14137e5e3b07797ad9e256170c` (2026-11-09 13:39:27 +0530, `fix(REDB1-51)...`). Working tree clean except untracked `qa-knowledge/` itself. See `overview.md` § Repository/revision.
2. **offers.md inventory-commit contradiction resolved** by reading `offers.service.ts:904-1127` directly: acceptance DOES commit inventory, unconditionally, at `incrementCommitted` (`:1124`, step 12/15 of `acceptOffer`) — after capture+order-creation+status-flip succeed. The "acceptance commits no inventory" source comment (`:921`) is about the narrow concurrent-accept race window before that step is reached, not a claim it's never committed. Correction callout added in `modules/offers.md` under Prior-incident evidence, plus an inline pointer at the step-3 mention.
3. **Idempotency corrected** in `overview.md`: the old text ("the API has no idempotency keys yet") uncritically copied `apps/mobile/CLAUDE.md`'s framing without checking source, and was wrong as a blanket claim. Verified via direct grep of `orders.service.ts`/`offers.service.ts`/`payments.service.ts`/`connect.service.ts`: **Stripe-operation idempotency is extensively implemented and unit-tested** (checkout, offer holds, Connect transfers/reversals/refunds/tax-transactions all carry deterministic Stripe idempotency keys). **Generic API-request-level idempotency (an `Idempotency-Key` header / platform middleware) is genuinely absent** — zero matches anywhere in `apps/api/src`. These are two different things; `overview.md` now documents both precisely with citations and instructs every module doc to specify which (if either) applies rather than reusing the old blanket phrasing.
4. **Endpoint-inventory reconciled against actual analysis depth**, not doc existence. Method: (a) automated regex cross-check — every endpoint's exact method+path string must appear in its module's `.md`; (b) heading-structure check (`### `/`## ` counts) to catch a doc that mentions a path in passing vs. gives it a real section; (c) manual read of `offers.md` in full (already done resolving #2) plus spot-reads of `orders.md`/`disputes.md`/`payment-methods.md`/`events.md`'s endpoint-summary sections to confirm topically-organized docs (not one-header-per-route) still cover every endpoint with real depth; (d) grep across all 16 docs for hedge language ("could not determine", "unclear", "not verified") — found none that indicate an unanalyzed endpoint (only documented business-ambiguity findings and one explicit out-of-scope cross-reference in `listings.md`, both fine). **Result**: all 182 endpoints across the 16 already-written modules (`auth`, `users`, `sellers`, `connect`, `listings`, `inventory`, `offers`, `orders`, `disputes`, `payments`, `payment-methods`, `shipping`, `messaging`, `reviews`, `notifications`, `events`) set to `"status": "analyzed"` in `endpoint-inventory.json`, each with a `verification` field describing the check. The remaining 106 endpoints (15 modules with no doc yet) stay `"pending"`. No endpoint was marked analyzed on doc-existence alone.
5. **Docs-survey correction**: the original `overview.md` docs survey used `find docs -maxdepth 1`, missing `docs/fix/` (100+ per-ticket write-ups) and `docs/features/` (80+ feature specs) entirely. These are real and were the actual source `offers.md` drew its BRI-citation depth from — not fabrication, as initially suspected on first read. `overview.md` now flags this correction and names which of the 16 already-written docs may under-cite `docs/fix/`/`docs/features/` for their own module and should be spot-checked when touched again.

### Remaining work, in the order it will be executed

1. ~~`help-articles.md`~~ **DONE 2026-11-10** — 2 endpoints, no persistence (live Intercom proxy), full analysis written, both endpoints set `analyzed` in `endpoint-inventory.json`. notifications-support batch (notifications, events, help-articles) is now fully module-documented; still needs its 6 fragment files.
2. ~~`health.md`, `seed.md`~~ **DONE 2026-11-10** — health is a pure liveness check (no dependency pings, source-verified). seed is additive/idempotent-only (zero deleteMany/truncate/raw-SQL found across all 765 lines, 21 upsert call sites) but has **zero authentication**, gated only by `NODE_ENV !== 'production'` — flagged as BR-SEED-002. Both endpoints set `analyzed`. infra-misc batch is now fully module-documented; still needs its 6 fragment files.
3. ~~`categories.md`, `brands.md`, `materials.md`, `promotions.md`, `feed.md`~~ **DONE 2026-11-10** — categories/brands/materials/promotions fully analyzed (set `analyzed`, 6 endpoints). `feed.md` set `partial` (6 endpoints) — contract fully confirmed (auth, DTOs, hidden-seller exclusion, curation/recompute idempotency, admin-curation-has-no-web-UI gap) but the 42KB `feed.repository.ts`'s ranking-math internals were not independently re-derived line-by-line; honestly flagged rather than claimed complete. discovery-taxonomy batch is module-documented; still needs its 6 fragment files.
4. ~~`saved-searches.md`, `recent-searches.md`, `addresses.md`~~ **DONE 2026-11-10** — all 16 endpoints `analyzed`. Notable: this resolved an open question — the ZIP↔city↔state consistency check is genuinely server-enforced (DTO class-level validator + service-layer completion-from-stored-row on partial edits), not merely a client-side mirror as earlier hypothesized. Also found: Shippo deliverability check fails open on outage, fails closed on an active "undeliverable" verdict. search-prefs batch is module-documented; still needs its 6 fragment files.
5. ~~`ai.md`, `embeddings.md`, `uploads.md`~~ **DONE 2026-11-10** — all 18 endpoints `analyzed`. Key findings: uploads storage is real S3 (corrected a speculative local-disk hypothesis from the original agent brief, never landed in overview.md); every upload read-route is unauthenticated-by-filename-obscurity including dispute evidence photos (96-bit random names + 1h presigned URLs, flagged in gaps); `/ai/regenerate` is fully built+tested on both ends but has no live mobile UI entry point; `checkProhibited` fails closed on DB error (opposite direction from Shippo/Intercom's fail-open pattern elsewhere). ai-media batch is module-documented; still needs its 6 fragment files.
6. ~~`admin.md`~~ **DONE 2026-11-10** — 56 endpoints, 42 `analyzed` (full service-method depth) + 14 `partial` (controller/DTO-level read, documented honestly, listed in `endpoint-inventory.json`). Guard verified uniform (`JwtAuthGuard`+`RolesGuard`+`@Roles(Role.ADMIN)`, no exceptions, confirmed by reading the full 566-line controller). Key findings: `updateOrderStatus`/`resolveDispute`/`issueRefund`/`retryPayoutReversal` all converge on the same two shared chokepoints; `deleteSubcategory`/`deleteType` have no listing-reference guard while `deleteCategory`/`deleteBrand` do (asymmetry flagged, unresolved); `PATCH /admin/users/:id/role` can mint new admins with no extra confirmation step (highest privilege-escalation risk in the module); admin surface is fragmented across 5 controllers under `admin/*` (confirmed, not this module's bug).

**All 31 module docs are now complete** (16 from before interruption + 15 written this session). Every endpoint in `endpoint-inventory.json` has a non-"pending" status (`analyzed` or `partial`, with a `verification` field). Remaining work is pure consolidation — no more fresh module analysis needed before the final report.

## ✅ Consolidation complete, 2026-11-10

All 5 root-level deliverables are written, each pulling from all 31 `modules/*.md` docs directly (the intermediate per-batch `fragments/*.json`/`*.md` files some early module docs still reference — e.g. `catalog-listing.*`, `notifications-support.*` — were superseded by this direct consolidation and were never produced; do not go looking for them, see `gaps-and-conflicts.md` § 7):

- `business-rules.json` — 352 rules across all 31 modules + 2 cross-cutting entries, reusing the 99 rules from the 3 pre-interruption fragments (offers, orders+disputes, payments+payment-methods+shipping) verbatim and adding 253 newly-derived entries for the other 28 modules.
- `gaps-and-conflicts.md` — 43 code-only gaps, 18 gaps with a corroborating open Linear ticket, 6 code-vs-ticket conflicts, 7 cross-module enforcement inconsistencies, 7 dead/unreachable-code findings, plus documentation corrections and execution blockers.
- `flows.md` — 11 end-to-end business flows with step-by-step endpoint sequences and data handoffs.
- `dependency-map.json` — 2 generic setup patterns + 6 fully-worked flow-level dependency chains (offer-accept, offer-expiry, Buy-Now checkout, dispute full-cycle, account deletion, messaging-block) + 4 explicitly unresolved dependency questions.
- `test-scenarios.md` — ~95 evidence-backed scenarios across auth, users, offers, orders, disputes, listings, inventory, messaging, reviews, sellers/connect, admin, uploads/AI, and seed/embeddings, each tagged by expectation source ([CODE]/[TICKET]/[CODE≠TICKET]/[GAP]).

### Final endpoint-inventory.json reconciliation

- **288 discovered, 288 accounted for, 0 pending.**
- **268 `analyzed`** (full service-method-depth read, guard/business-logic/error-handling confirmed).
- **20 `partial`**: 6 `feed` endpoints (contract fully confirmed; the ranking algorithm's internal query construction in the 42KB `feed.repository.ts` was not independently re-traced line-by-line) + 14 `admin` endpoints (simple list/CRUD reads given a lighter controller/DTO-level pass given the module's 56-endpoint scope, each individually noted in `modules/admin.md`).
- **0 endpoints remain unanalyzed.** No endpoint was marked `analyzed` on module-doc existence alone — see the 2026-11-10 reconciliation entry above this one for the verification method.

### Verified during this session's quality pass
- Every one of the 31 modules in `endpoint-inventory.json` has a corresponding `modules/*.md` file, and vice versa (no orphans either direction).
- Spot-checked 2 `business-rules.json` citations (`BR-ORDERS-002`, `BR-USERS-009`) directly against source — both accurate (exact exception class/message and method name/line confirmed).
- All 5 JSON-format deliverables (`endpoint-inventory.json`, `business-rules.json`, `dependency-map.json`) parse as valid JSON.

### Known limitations carried into the final report (not resolved by this analysis, by design)
- The `shippo` MCP server failed to connect all session — no live inspection of Shippo's own sandbox/webhook tooling was possible.
- Dependency chains are mapped in depth for the highest-value/highest-risk flows (6 fully worked), not mechanically for all 288 endpoints — most simple CRUD/read endpoints share one of the two documented generic patterns instead.
- Test scenarios are derived from every confirmed business rule and gap (not from routine CRUD boundary-testing for every endpoint) — see `test-scenarios.md`'s own "explicitly not scenario'd" section for the exact scoping rationale.
- Runtime behavior was never verified by execution (no app run, no API called) — every finding is "confirmed by reading the code," consistent with the task's own constraints.
7. Fragments for all 14 batches (most don't exist yet, including for the 16 already-analyzed modules — these can be synthesized from the existing rich `.md` content rather than re-researched).
8. Consolidate all fragments into `business-rules.json`, `dependency-map.json`, `flows.md`, `test-scenarios.md`, `gaps-and-conflicts.md`.
9. Final report: completed/partial/unresolved endpoint counts + blockers.

Progress is checkpointed in this file after each module below.

## Module batches

Each batch is one subagent run, writing:
- `qa-knowledge/modules/<module>.md` (or one file per batch covering multiple small modules)
- `qa-knowledge/fragments/<batch>.business-rules.json`
- `qa-knowledge/fragments/<batch>.dependency-map.json`
- `qa-knowledge/fragments/<batch>.test-scenarios.md`
- `qa-knowledge/fragments/<batch>.gaps.md`
- `qa-knowledge/fragments/<batch>.flows.md`

Coordinator merges fragments into the aggregate `business-rules.json`, `dependency-map.json`, `test-scenarios.md`, `gaps-and-conflicts.md`, `flows.md`, and flips `endpoint-inventory.json` entries to `analyzed`/`partial` once merged.

| # | Batch | Modules | Endpoints | Status |
|---|---|---|---|---|
| 1 | identity | auth, users | 22 + 21 = 43 | **interrupted** — see per-file table below |
| 2 | seller-onboarding | sellers, connect | 26 + 5 = 31 | **interrupted** |
| 3 | catalog-listing | listings (+ listing-stats), inventory | 26 + 4 = 30 | **interrupted** |
| 4 | offers | offers | 8 | **interrupted** |
| 5 | orders-disputes | orders, disputes | 13 + 11 = 24 | **interrupted** |
| 6 | payments-shipping | payments, payment-methods, shipping (+ shippo-webhook) | 1 + 3 + 2 = 6 | **interrupted** |
| 7 | messaging | messaging, messaging.admin + gateways (messaging.gateway, realtime.gateway) | 21 | **interrupted** |
| 8 | reviews | reviews | 14 | **interrupted** |
| 9 | discovery-taxonomy | feed (+ curation), categories, brands, materials, promotions | 6 + 3 + 1 + 1 + 1 = 12 | **not started — full restart** |
| 10 | notifications-support | notifications, events, help-articles | 4 + 1 + 2 = 7 | **interrupted** |
| 11 | search-prefs | saved-searches, recent-searches, addresses (+ us-places) | 6 + 3 + 7 = 16 | **not started — full restart** |
| 12 | admin | admin | 56 | **not started — full restart** |
| 13 | ai-media | ai, embeddings, uploads | 3 + 2 + 13 = 18 | **not started — full restart** |
| 14 | infra-misc | health, seed | 1 + 1 = 2 | **not started — full restart** |

## ⚠️ Interruption 2026-11-10 ~09:00 SLST

All 14 batch agents were launched in parallel (4 waves) and ALL were killed mid-task by the account hitting its session rate limit (`HTTP 429`, resets **1:20pm Asia/Colombo / SLST**, ~4h after this note). This is a hard account-level limit, not a per-agent issue — relaunching immediately will fail the same way. **Do not retry before the reset time.**

Verified actual filesystem state (not agent self-reports — agents can claim more than they wrote before being killed) as of the interruption:

### Per-file resume table (authoritative — supersedes the batch-status column above)

| Batch | `modules/*.md` written | `fragments/<batch>.*` written | What's left |
|---|---|---|---|
| identity | `auth.md` ✓, `users.md` ✓ | none (0/6) | Write all 6 `identity.*` fragments. Module docs are done — a resume agent can read them instead of re-researching, UNLESS spot-checking shows they're incomplete (check each file's last section for a mid-sentence cutoff). |
| seller-onboarding | `sellers.md` ✓, `connect.md` ✓ | none (0/6) | Write all 6 `seller-onboarding.*` fragments. Same spot-check caveat. |
| catalog-listing | `listings.md` ✓, `inventory.md` ✓ | none (0/6) | Write all 6 `catalog-listing.*` fragments. Same spot-check caveat. |
| offers | `offers.md` ✓ | `.business-rules.json` ✓, `.dependency-map.json` ✓, `.flows.md` ✓ | Write `offers.test-scenarios.md`, `offers.gaps.md`, `offers.endpoint-status.json`. |
| orders-disputes | `orders.md` ✓, `disputes.md` ✓ | `.business-rules.json` ✓ | Write `orders-disputes.dependency-map.json`, `.test-scenarios.md`, `.gaps.md`, `.flows.md`, `.endpoint-status.json`. |
| payments-shipping | `payments.md` ✓, `payment-methods.md` ✓, `shipping.md` ✓ | `.business-rules.json` ✓ | Write `payments-shipping.dependency-map.json`, `.test-scenarios.md`, `.gaps.md`, `.flows.md`, `.endpoint-status.json`. |
| messaging | `messaging.md` ✓ | none (0/6) | Write all 6 `messaging.*` fragments. Spot-check the doc covers both gateways per the original brief. |
| reviews | `reviews.md` ✓ | none (0/6) | Write all 6 `reviews.*` fragments. |
| notifications-support | `notifications.md` ✓, `events.md` ✓, **`help-articles.md` MISSING** | none (0/6) | Write `help-articles.md` + all 6 `notifications-support.*` fragments. |
| discovery-taxonomy | none of `feed.md`/`categories.md`/`brands.md`/`materials.md`/`promotions.md` exist | none | **Full restart** — relaunch with the original wave-3 prompt unchanged. |
| search-prefs | none of `saved-searches.md`/`recent-searches.md`/`addresses.md` exist | none | **Full restart** — relaunch with the original wave-3 prompt unchanged. |
| admin | `admin.md` does not exist | none | **Full restart** — relaunch with the original wave-3 prompt unchanged. This is the largest batch (56 endpoints) — prioritize re-running it early. |
| ai-media | none of `ai.md`/`embeddings.md`/`uploads.md` exist | none | **Full restart** — relaunch with the original wave-4 prompt unchanged. |
| infra-misc | none of `health.md`/`seed.md` exist | none | **Full restart** — relaunch with the original wave-4 prompt unchanged (includes the seed-endpoint data-safety finding, still needed). |

### Resume plan (do this, in this order, after 1:20pm SLST)

1. **Full restarts first** (discovery-taxonomy, search-prefs, admin, ai-media, infra-misc) — these need the complete original agent prompt (they're preserved verbatim in this session's transcript; if resuming in a new session, reconstruct from this file's batch table + `endpoint-inventory.json`'s per-module endpoint lists + `overview.md`'s architecture notes — the prompts followed a consistent template: read overview.md + progress.md + apps/mobile/CLAUDE.md first, then the full "ANALYZE EACH ENDPOINT" checklist from the user's original task, then write modules/*.md + 6 fragment files per batch).
2. **Fragments-only resumes** (identity, seller-onboarding, catalog-listing, messaging, reviews, notifications-support) — lighter-weight agents that read the EXISTING `modules/*.md` (first spot-checking it isn't truncated mid-sentence) and derive the 6 fragment files from it, rather than re-reading the whole backend/frontend from scratch. Cheaper and faster than a full restart.
3. **Partial-fragments resumes** (offers, orders-disputes, payments-shipping) — same as above but only the 3-5 missing fragment files per batch.
4. Only after all 14 batches have complete module docs + complete fragment sets: merge all `fragments/*.json`/`*.md` into the aggregate `business-rules.json`, `dependency-map.json`, `test-scenarios.md`, `gaps-and-conflicts.md`, `flows.md`, flip `endpoint-inventory.json` statuses, then run the final quality-check pass (endpoint count reconciliation, cross-checks) described in the original task.

Do not re-run the inventory-generation script or re-survey the repo structure — `endpoint-inventory.json` and `overview.md` are already correct and durable.

Total: 288 endpoints (43+31+30+8+24+6+21+14+12+7+16+56+18+2 = 288 ✓).

## Resume instructions

If interrupted mid-sweep:
1. Check this table for `pending` rows — those batches haven't been launched or haven't returned.
2. Check `qa-knowledge/fragments/` for `<batch>.*` files that exist but aren't yet merged into the aggregate files — merge those before re-running a batch.
3. Check `endpoint-inventory.json` `status` field per endpoint (`pending`/`partial`/`analyzed`) — this is the authoritative per-endpoint tracker, independent of batch-level status in this table.
4. Do not re-derive the endpoint inventory from scratch — `build_inventory.py` logic is recorded in this repo's session scratchpad only; the generated `endpoint-inventory.json` is the durable artifact. If it needs regenerating, re-run the same `@Controller`/HTTP-method-decorator grep across `apps/api/src/**/*.controller.ts` and reapply the file→prefix map in `overview.md`'s architecture section (or reconstruct from the controller files directly — the map is mechanical: `@Controller('prefix')` + each method decorator's path).
5. Quality pass (reconciliation, counts, cross-checks) happens only after all 14 batches report back — don't run it early.
