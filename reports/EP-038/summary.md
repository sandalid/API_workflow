# EP-038 - GET /listings/:id - evidence summary

## Runs

| Run ID | Role | Auth | Status | Spec version/hash | Fixtures states | Execution errors |
|---|---|---|---|---|---|---|
| RUN-20261109-150351-EP-038-user | user | ok (otp) | completed | 1.0 / `8c58e57f...` | active, approved, draft, inactive, pending_approval, sold | 0 |
| RUN-20261109-150440-EP-038-admin | admin | ok (password) | completed | 1.0 / `8c58e57f...` (same hash) | active, approved, draft, inactive, pending_approval, sold | 0 |
| RUN-20261109-150516-EP-038-anon | anon | anonymous-explicit | completed | 1.0 / `8c58e57f...` (same hash) | active, approved, draft, inactive, pending_approval, sold | 0 |

All three runs completed, 0 execution errors, identical spec hash across roles. No fixtures were ever provided in `rejected`, `reserved`, or soft-deleted (`deletedAt` set) states for any role — this is the single prerequisite gap driving all 8 BLOCKED verdicts.

## Verdict counts (PASS 21 / FAIL 11 / BLOCKED 8 / NOT RUN 1) — what they do and do not prove

- **PASS (21)** — proves: status-code-in-range checks succeeded (`not_a_server_error`, `max_response_time`), and for a handful of cases a specific business-rule status (200/404) matched the code's documented behavior (e.g. TC-038-011/012 owner/admin see `draft`; TC-038-019 anon gets 404 on `pending_approval`; TC-038-048 nonexistent id returns 404 with `message: 'Listing not found'`, TC-038-056 confirms `offerCount` absent). **PASS never proves response-schema conformance here** — every 200-status case that would need schema validation is BLOCKED instead (see below), because the spec declares no schema for the 200 response (`TC-038-003/006/010`, verdicts.json detail: `"spec declares no schema for GET /listings/{id} -> 200; 'response_schema_conformance' passed vacuously"`). A 200 status alone does not confirm field content, ownership-gating correctness beyond the specific assertion tested, or absence of other dead fields.
- **FAIL (11)** — see grouped root causes below. Two of the eleven (TC-038-013, TC-038-016) are business-rule mismatches against the sheet's literal title, not necessarily app defects — the audit records these as recorded requirement conflicts (draft-visibility) and an unclear case (inactive-visibility), not settled bugs.
- **BLOCKED (8)** — proves nothing either way; prerequisite fixtures/spec content were missing. 3 are schema-conformance checks blocked by the spec's lack of a 200 schema; 5 are business/coverage cases blocked by missing `rejected`/`reserved`/soft-deleted fixture resources.
- **NOT RUN / no evidence (1)** — TC-038-057 (sending a foreign-resource-type id, e.g. an order id, as the `:id` path param) was never exercised by any of the three runs; no scenario in any evidence.json matches it.

## Evidence gaps and execution errors

- No execution errors in any of the 3 runs (manifest `execution_errors: []` for user/admin/anon).
- Auth for user and admin roles succeeded (`bootstrap_phase: success`); anon is explicitly unauthenticated by design (role under test) — not a failure.
- Fixture snapshot (`dda4cda766a8...`, identical across all 3 runs) only contains `active, approved, draft, inactive, pending_approval, sold` — **no `rejected`, no `reserved`, no soft-deleted (`deletedAt`) listing** was ever available to any role. This blocks: TC-038-023 (rejected hidden, anon), TC-038-052 (rejected owner-view, user), TC-038-024/047 (soft-deleted hidden, anon/admin), TC-038-055 (reserved visible, anon).
- Response-schema conformance could not be checked for any 200 response in any role (TC-038-003/006/010) because the OpenAPI spec declares no schema for the 200 response on this operation (confirmed directly by spec-only checks TC-038-034/035, both FAIL as "spec does not declare 404 response" / "does not declare schema for 200").
- TC-038-057 (foreign-type id as path param) has no matching executed scenario in any run — Schemathesis's fuzzing did not happen to produce this case; needs a manual/other-method test.

## Fields / params to remove or fix

| # | Item | Kind | Source (verdict/ST code + audit) | Evidence | Recommendation | Confidence |
|---|---|---|---|---|---|---|
| 1 | `id` path param | request param | N/A — used in every call path | audit "Declared Contract", `listings.controller.ts:376-377` | KEEP | high |
| 2 | Only `pending_approval` is gated from non-owner/non-admin; `draft`/`rejected`/`inactive` return full DTO to anyone | business-rule branch | TC-038-013 FAIL (anon, "status 200 expected in [404]"), TC-038-016 FAIL (anon), audit Finding #1 + Source agreement matrix row 1 ("Conflict — sheet vs. code+tests+domain doc") | `listings.service.ts:786` gate only checks `HIDDEN_FROM_PUBLIC_STATUS === 'pending_approval'`; intentionally tested at `listings.service.spec.ts:965-972` | Potential defect — **clarify requirement first** (is sheet title wrong, or is BRI-44 wrong). Do not FIX CODE or REMOVE until PO/QA resolves the conflict; if sheet is wrong, FIX SPEC/sheet title | high (conflict is clearly documented; which side is "right" is not ours to decide) |
| 3 | Soft-deleted listing 404s for **everyone including owner/Admin** (not just non-owners) | business-rule branch | TC-038-024/047 BLOCKED (no soft-deleted fixture to actually run this), audit Finding #2 + Source agreement matrix row 4 ("Conflict + implicit spec-gap") | `listings.repository.ts:692-704` (`NOT_DELETED` filter applies before any role check) | Potential defect — clarify first. Cannot be confirmed FAIL/PASS without a soft-deleted fixture (currently BLOCKED, not tested) | medium (code path confirmed by audit/code read, but not exercised live in any of these 3 runs) |
| 4 | 200 response has no documented schema in spec | response/contract | TC-038-035 FAIL (`SPEC:200-schema`), TC-038-003/006/010 BLOCKED as a result, audit Finding #9 | verdicts.json: `"spec 1.0: GET /listings/{id} does NOT declare schema for 200"` | FIX SPEC — add a response schema so schema-conformance can actually run instead of passing vacuously | high |
| 5 | 404 response not documented in spec | response/contract | TC-038-034 FAIL (`SPEC:404-documented`), TC-038-008/037/038 FAIL (ST103 status_code_conformance) | verdicts.json: `"spec 1.0: GET /listings/{id} does NOT declare response for 404"` | FIX SPEC — document the 404 case (two real reasons: not-found id, hidden `pending_approval`) | high |
| 6 | No `security`/auth requirement documented in spec for this route | auth/contract | audit Finding #9 / Source agreement matrix row 5 | `optional-jwt-auth.guard.ts` behaviour vs 0 `security` occurrences in openapi.json (audit) | FIX SPEC — document optional-bearer auth | medium (spec-wide pattern, not unique to this endpoint) |
| 7 | `ratingAvg`, `reviewCount` returned but unread by any client off this endpoint | response field | audit Finding #3 (needs_other_method TC-038-028) | `listings.service.ts:291-292`; grep across mobile/web types found no reads off this DTO | MAKE OPTIONAL / VERIFY WITH OTHER CLIENT FIRST — do not REMOVE outright (shared serializer with other endpoints) | medium |
| 8 | `watchersCount` returned but unread (separate `/listings/:id/watchers` view-count flow supplies the UI instead) | response field | audit Finding #4 (needs_other_method TC-038-029) | `listingsApi.ts:62` declares it, no `.watchersCount` read in prod code | MAKE OPTIONAL / VERIFY WITH OTHER CLIENT FIRST | medium |
| 9 | `likeCount`, `commentCount` required on shared `Product` type but unread off a listing object | response field | audit Finding #5 (needs_other_method TC-038-030) | `types\domain.ts:76-77`; zero non-test reads | KEEP (shared type with browse/search/feed `toListingListDto` — audit explicitly says not unique to this endpoint) | medium |
| 10 | 405 on unsupported method missing required `Allow` header | protocol/framework | TC-038-001 (user), TC-038-004 (admin), TC-038-007/036 (anon) all FAIL — `"header allow present -> absent"` | verdicts.json assertions for all four cases | FIX CODE — framework-level (Nest/Express default), low severity but affects all 3 roles consistently | high |

## Defects (see bug report)

See BUG-EP038-01 through 03 below.

## Unresolved expectations and conflicts

- **TC-038-013** (Draft listing NOT visible to anonymous) — **Conflict**. Sheet title says draft must be hidden from non-owner/non-admin; code (`listings.service.ts:786`, gated only on `pending_approval`) and existing unit test (`listings.service.spec.ts:965-972`) say draft is intentionally public. A FAIL here is a "potential defect — clarify first," not a confirmed bug.
- **TC-038-016** (Inactive listing hidden from anonymous, per sheet intent) — **Unclear**. Same code path as above; sheet title doesn't name `inactive` explicitly but implies it via "draft or removed." Needs PO/QA clarification before treating as a defect.
- **TC-038-023** (Rejected listing not visible to non-owner/non-admin) — **Conflict**, and also BLOCKED (no `rejected` fixture was available to actually execute it in any run).
- **TC-038-047** (Admin opens a soft-deleted listing, Flow 26) — **Conflict**, and also BLOCKED (no soft-deleted fixture available). Sheet title implies admin should still see a "removed" listing; code 404s for admin too (`listings.repository.ts:692-704`).

These four cases must not be reported as confirmed app defects until the sheet title vs. BRI-44/BRI-366 product-decision conflict is resolved by QA/PO, per the audit's Source agreement matrix.

## Cases needing another execution method

From verdicts.json `needs_other_method` (16 legacy cases, no Schemathesis execution path):
- TC-038-025, 026, 027 — visibility-matrix narrative cases already covered by executed BR cases above; need no separate action, but flagged as not independently automatable.
- TC-038-028, 029, 030, 050 — dead-field static review (ratingAvg/reviewCount, watchersCount, likeCount/commentCount, general "tracked not tested") — needs static code review, not Schemathesis.
- TC-038-031 — `ResumeDraft.tsx` no-token call depending on draft staying ungated — needs mobile client test, not API-only.
- TC-038-032, 033, 041, 045 — additional call-site coverage (Offers item cards, seller-web edit page) — needs client-side/manual verification per audit Findings #7/#8.
- TC-038-049 — confirming all fields the apps actually read are present — needs cross-referencing client code, not a Schemathesis assertion.
- TC-038-051 — expired/invalid Bearer token behavior — needs a manual request with a crafted expired token.
- TC-038-053 — cross-account non-owner access to a `pending_approval` listing — needs a second seller account fixture.
- TC-038-054 — cache-staleness after admin approval — needs a sequential two-step test (approve then re-fetch), not a single fuzzed request.
- TC-038-058 — unknown/extra query params ignored — flagged explicitly for **Postman**, not a Schemathesis case.

## Could not verify

- Whether soft-deleted listings genuinely 404 for owner/Admin as the audit's static code read claims (`listings.repository.ts:692-704`) — BLOCKED in all 3 runs (TC-038-024, 047) for lack of a soft-deleted fixture. Code-level claim only, not live-evidence-backed for this execution.
- Whether `rejected` listings are treated like `draft`/`inactive` (public) in a live request — BLOCKED (TC-038-023, 052), no `rejected` fixture in any run.
- Whether `reserved` listings are visible to anon — BLOCKED (TC-038-055), no `reserved` fixture.
- Response-schema conformance for any 200 response, for any role — BLOCKED for all three (TC-038-003/006/010), spec declares no schema.
- TC-038-057 (foreign-resource-type id as path param, security/negative case) — no evidence in any of the 3 runs; not exercised.
- Whether a dynamic/spread consumer in any client reads `ratingAvg`/`reviewCount`/`watchersCount`/`likeCount`/`commentCount` — audit explicitly flags this as unverifiable by static grep alone (audit "Could not verify" section).
