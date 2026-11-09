# EP-032 - GET /brands - evidence summary

## Runs

| Run id | Role | Auth | Status | Spec version/hash | Execution errors |
|---|---|---|---|---|---|
| RUN-20261109-184340-EP-032-user | user | ok (otp bootstrap) | completed | 1.0 / `8c58e57f...9bbd6d` | 0 |
| RUN-20261109-184418-EP-032-admin | admin | ok (password bootstrap) | completed | 1.0 / `8c58e57f...9bbd6d` | 0 |
| RUN-20261109-184435-EP-032-anon | anon | anonymous-explicit | completed | 1.0 / `8c58e57f...9bbd6d` | 0 |

All three runs share the same spec snapshot/hash. No execution errors on any run — evidence is structurally complete for all three roles; the gaps below are capture-depth gaps (body truncation, no spec schema), not auth or execution failures.

## Verdict counts (PASS 3 / FAIL 1 / BLOCKED 1 / NOT RUN (partial) 3 / no matching evidence 1)

- **PASS (3):** TC-032-001 (anon, 200, status+response-time satisfied), TC-032-015 (anon with malformed/no token still 200), TC-032-017 (anon catch-all: no 5xx, under time budget). These prove the endpoint is reachable anonymously, returns 200, responds under the time budget — not response-body correctness (only status/process-level checks were asserted).
- **FAIL (1):** TC-032-016 — anon TRACE → 405 but missing the `Allow` header required by RFC 9110.
- **BLOCKED (1):** TC-032-011 — schema-conformance check on anon 200 response. Blocked because the OpenAPI spec declares no response schema at all for `GET /brands` → 200, so the check "passed vacuously" rather than validating anything real.
- **NOT RUN (partial) (3):** TC-032-002 (user), TC-032-004 (admin), TC-032-010 (anon, field-coverage). All got 200 confirmed but every `body_json` assertion is unperformed — **response body was truncated in evidence capture**. This is an evidence-capture limitation, not a pass or fail; field content/shape is unverified for user and admin roles entirely.
- **No matching evidence (1):** TC-032-003 ("identical-response:other") — no scenario executed in any run.

## Evidence gaps and execution errors

- No auth failures, no manifest errors, no execution errors in any of the 3 runs.
- **Body-truncation gap:** affects every field-content check for user/admin roles and the full 7-field coverage check for anon — cannot be read as PASS or FAIL.
- **Spec-schema gap:** `GET /brands` has no response schema in OpenAPI at all (`"200":{"description":""}`, no content/schema) — confirmed independently against `openapi.json`. This means `response_schema_conformance` cannot meaningfully validate anything for any role.
- TC-032-003 has zero executed evidence across all three runs.

## Fields / params to remove or fix

`GET /brands` takes zero request parameters, so this is entirely about response fields and contract/behavior gaps.

| # | Item | Kind | Source | Evidence | Recommendation | Confidence |
|---|---|---|---|---|---|---|
| 1 | No response schema declared for `GET /brands` → 200 | Spec gap | TC-032-011 BLOCKED | `brands.controller.ts:10-14` has no `@ApiResponse`/DTO | FIX SPEC — add a response schema listing `id, name, slug, logo, navigationTab, createdAt, itemCount` | High |
| 2 | `slug`, `logo` returned by backend but dropped by the only confirmed consumer (mobile) before reaching any screen; no web call site exists | Dead response field | Audit Finding #3 | `brands.repository.ts:22`; mobile `brandsApi.ts` maps them out | MAKE OPTIONAL / FIX SPEC to document as present-but-unused; do not hard-REMOVE without confirming no undocumented consumer relies on them | Medium |
| 3 | `navigationTab`, `createdAt` returned by backend but never even typed by the mobile client | Dead response field | Audit Finding #4 | `brands.repository.ts:22`; mobile `RawBrand` type doesn't declare either | Same as above — FIX SPEC to document, low-priority REMOVE candidate only after confirming no other consumer | Medium |
| 4 | TRACE on `/brands` returns 405 without required `Allow` header | Behavior gap (framework-level) | TC-032-016 FAIL + 2 new evidence-backed cases (user, admin) | all 3 roles, same outcome | FIX CODE — platform-level, add middleware/exception mapping for `Allow` on 405s app-wide | High |
| 5 | QUERY method returns 404 instead of 405 | Behavior gap (framework-level, same pattern as EP-033) | unmatched_failures across all 3 roles, no existing TC | consistent 404 across user/admin/anon | FIX CODE/SPEC — cross-endpoint platform routing fix, not EP-032-specific | Medium |
| 6 | Response ordering: code sorts alphabetically; app code comments and `brand-drill-down.md` assume admin-curated/insertion order; `Brand` model has no `sortOrder` column at all | Business-rule conflict (CF-032-01, CF-032-02) | TC-032-007/008 unresolved | `brands.repository.ts:14`; `schema.prisma:514-521`; `Explore.tsx:52-55`; `BrandListing.tsx:26-29`; `brand-drill-down.md:16` | Clarify requirement with product/doc owner first — not Schemathesis-provable either way | N/A — conflict |
| 7 | 429 (rate limit) and 5xx paths undocumented in spec | Spec gap | Audit Source-agreement-matrix | global `ThrottlerGuard`, `AllExceptionsFilter` | FIX SPEC — document 429/5xx as possible responses | Low |

## Defects (see bug report)

Two concrete, evidence-backed FAILs (unsupported-method handling, affecting user/admin/anon identically) and one unresolved requirement conflict flagged as a potential defect pending clarification.

## Unresolved expectations and conflicts

- **CF-032-01 / TC-032-007, TC-032-008 (Conflict):** App code comments and `docs\features\brand-drill-down.md:16` assert the endpoint returns "the admin's own insertion/curated order." Code sorts alphabetically. Directly affects the guest Explore "first 6 brands" taster rail. **Not Schemathesis-provable as a FAIL** — routed to `needs_other_method`/`unresolved_expectations`, not a confirmed bug. Treat as a potential defect requiring product clarification first.
- **CF-032-02:** The `Brand` model has no `sortOrder`/order column at all — unlike `Material`, which has one plus a dedicated ordering endpoint. The admin-only brand read also hard-sorts alphabetically. The doc's "admin-configured order" premise has no data model to support it today. Flag to product/PO before filing any code-fix ticket for ordering.

## Cases needing another execution method

- TC-032-005 — `itemCount` correctness vs `LIVE_LISTING_WHERE` filtering — Manual
- TC-032-006 — brand with 0 live listings still appears with `itemCount: 0` — Manual
- TC-032-007 — ordering (admin-curated vs alphabetical) — Manual (see conflict above)
- TC-032-008 — guest Explore taster rail ordering — Playwright
- TC-032-009 — confirm no `/brands/{id}` route exists — Postman
- TC-032-012 — 429 rate-limit burst behavior — Postman
- TC-032-013 — unexpected query params silently ignored — Postman
- TC-032-014 — malformed/injection junk on a zero-param endpoint — Postman

## Could not verify

- Field-level content of the response body for any role beyond "status 200" — TC-032-002 (user), TC-032-004 (admin), TC-032-010 (anon) all have `body_json` checks unperformed due to body truncation in evidence capture.
- TC-032-003 ("identical-response:other") — no evidence executed in any run; cannot assess at all.
- Whether `response_schema_conformance` would catch any real contract violation — moot, since the spec declares no schema (TC-032-011 BLOCKED).
- Whether `Filters.tsx`/`BrandListing.tsx` display `itemCount` in JSX beyond passing the array through (grep-only check, carried from audit).
- Git history on the `orderBy` line to determine if it predates the doc (carried from audit).
