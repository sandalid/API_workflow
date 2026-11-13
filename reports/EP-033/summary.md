# EP-033 - GET /categories - evidence summary

Runs:

| run id | role | auth | status | spec version | errors |
|---|---|---|---|---|---|
| RUN-20261113-095130-EP-033-anon | anon | anonymous-explicit | completed | 1.0 (sha256 8c58e57f...) | 0 |
| RUN-20261113-095151-EP-033-user | user | ok (otp) | completed | 1.0 (sha256 8c58e57f...) | 0 |
| RUN-20261113-095214-EP-033-other | other | ok (otp) | completed | 1.0 (sha256 8c58e57f...) | 0 |
| RUN-20261113-095236-EP-033-admin | admin | ok (password) | completed | 1.0 (sha256 8c58e57f...) | 0 |

All four runs are valid evidence: no rate-limiting (429) or unreadable-run flags appear in the tally, manifest status is `completed` for all four, and `execution_errors: []` in every `run.json`. 6 requests per role per the tally (`GET statuses={'200': 3}` plus the TRACE/QUERY/OPTIONS unsupported-method cases), matching the request lists in `results_detail.csv` for each run.

## Verdict counts (PASS / FAIL / BLOCKED / NOT RUN) and what they do and do not prove

Per `verdicts.json`/`verdicts.md` (combined across the 4 runs, authoritative for per-case detail): **PASS 10 | FAIL 0 | BLOCKED 1 | NOT RUN (partial) 0 | no matching evidence 1**.

Per the pre-apply tally (workbook-level aggregate, 22 total cases before evidence.py ran): 10 BLOCKED, 12 NOT RUN, 12 with a matching spec, broken down by category as: Audit-derived BLOCKED 2; Business Rule BLOCKED 4, NOT RUN 3; Functional BLOCKED 1, NOT RUN 3; Negative BLOCKED 2, NOT RUN 1; Schema/Contract BLOCKED 1; Schemathesis NOT RUN 3; Security/Auth NOT RUN 2. The tally's category numbers describe the workbook's pre-run state and the `--all-runs` roles found; the verdicts.json PASS/FAIL/BLOCKED per-TC detail is the source for individual case outcomes.

PASS cases and what they prove:
- TC-033-001/002/003/004 (anon/user/other/admin identical 200 response) — status 200 and, for 002/003/004, `[0].id exists` — proves a 200 is returned to every role with an identical first category id (`RUN-20261113-095130...anon` cases `5gI6J3,HqxM9k,TOD5VZ`; `RUN-20261113-095151...user` cases `QymW3P,9SQJsf,fkNImp`; etc.). It does **not** prove full-body identity across roles (no cross-request diff is performed — flagged by the independent case review, `testcases\reviews\EP-033-review.md` finding #6, and not strengthened in this run).
- TC-033-005 (all-fields-present) — PASS with explicit existence checks for `id,name,slug,icon,image,sortOrder,createdAt,updatedAt` on `RUN-20261113-095130-EP-033-anon`, case `5gI6J3`. Proves the response shape matches the raw-Prisma contract described in the audit.
- TC-033-011 (unsupported method, TRACE) — PASS, `RUN-20261113-095130-EP-033-anon` case `VXpqmA`, status 405, asserting only `status in [404,405]` (no Allow-header assertion, per the pre-run loosening from the case-design review). This proves only that status falls in the accepted range — it does not prove RFC 9110 Allow-header compliance (see Bugs).
- TC-033-013/018/019/022 (unexpected query params, malformed token, generic non-5xx/response-time, injection-style query junk) — all PASS at status 200 on anon run, cases `5gI6J3,HqxM9k,TOD5VZ`.

BLOCKED:
- TC-033-015 (response schema conformance) — `kind: blocked`, reason: `check 'response_schema_conformance' was not performed on this request; spec declares no schema for GET /categories -> 200; passed vacuously`. This does NOT prove the response shape is correct against OpenAPI — there is nothing in the spec to validate against (`schemathesis\spec\openapi.pretty.json:1215-1219`, `200` response has empty `description` and no `schema` key).

No matching evidence (not a PASS, not a FAIL):
- TC-033-012 (unsupported method, POST) — `kind: none`, reason `no matching scenario executed`. Schemathesis's coverage phase generated TRACE/QUERY/OPTIONS as the "unspecified method" probes in all four runs (confirmed in every run's `results_detail.csv`), not POST specifically, so this case has no executed evidence either way.

## Evidence gaps and execution errors

- No execution errors in any of the four `run.json` files (`execution_errors: []`).
- Fixtures: all four runs share the same `fixtures.snapshot.json` (sha256 `887cedbf...`), whose only states/operations are listing states and `GET /listings/{id}` — there are zero `/categories`-specific fixtures (confirmed consistent with the audit's "Fixtures/accounts needed" section, which lists fixtures this endpoint would need but none exist in `fixtures.json`). This blocks any Schemathesis attempt at ordering, empty-taxonomy, legacy-category, or delete/409 scenarios — none of those are schema-driven inputs Schemathesis can synthesize without a seeded DB state.
- TC-033-015 is blocked purely by a spec gap (no response schema for 200), not by a runtime failure.
- TC-033-012 has no evidence because Schemathesis's coverage phase did not generate a POST request against `/categories` in any of the four runs (verified against all four `results_detail.csv` files — TRACE, QUERY, OPTIONS, and three GET variants are the only methods/cases present).

Coverage observed: all 4 roles produced identical 200 bodies at `/categories` (no role-based branching, consistent with the audit's "no guard" finding, `categories.controller.ts:6-14`). No 4xx/401/403 was ever observed for this endpoint in any run — consistent with it being a public, guard-less route. No 5xx was observed in any run.

## Fields / params to remove or fix

| # | Item | Kind | Source (verdict/ST code + audit) | Evidence | Recommendation | Confidence |
|---|---|---|---|---|---|---|
| 1 | `sortOrder` response field | response field | Audit finding #1; TC-033-005 PASS confirms it's present in the live body | `categories.repository.ts:17-19` (no `select`, so it's returned); mobile `categoriesApi.ts:72-81` mapper never reads `sortOrder` (per audit); TC-033-005 evidence shows `sortOrder: 0` present | KEEP for now / FIX CODE if trimming is desired later (contrast with `findTree()` at `categories.repository.ts:49-87`, which uses an explicit `select`) — not REMOVE, since this is a response over-exposure, not a broken param, and no client currently breaks from its presence | medium |
| 2 | `createdAt`/`updatedAt` response fields | response field | Audit finding #2; TC-033-005 PASS confirms presence | `categories.repository.ts:17-19`; mobile mapper (per audit) never references them | KEEP for now / FIX CODE (apply the same explicit-select pattern as `findTree()`) — minor over-exposure, not harmful, low business impact | medium |
| 3 | `parentId` on mobile `Category` client type | client-side field | Audit finding #6 (mobile-only, out of this endpoint's backend scope) | `types\domain.ts:32-40`; backend `Category` has no parent relation (`prisma\schema.prisma:543-565` per audit) | Out of scope for this backend endpoint's bug report — flag to mobile team only; no backend action | low (cited from audit, not independently re-verified in this run) |
| 4 | OpenAPI `200` response for `GET /categories` has no schema | spec | TC-033-015 BLOCKED; audit finding #7 | `schemathesis\spec\openapi.pretty.json:1215-1219`; TC-033-015 verdict `unchecked: check:response_schema_conformance ... spec declares no schema` | FIX SPEC — add a response schema for the array of Category objects so schema-conformance can be meaningfully checked in future runs | high |

No item here is recommended for REMOVE; the audit's "Looks unused but kept" section (covering `findAllBySlugs` and `icon`/`image`) is respected and not contradicted by anything in this run's evidence.

## Defects (see bug report)

See bugs.md. Zero FAIL verdicts were produced against any existing workbook test case in this run (PASS 10 / FAIL 0 / BLOCKED 1 / not matched 1). The bug report covers (a) Schemathesis's own `unsupported_method` (ST204) check, which failed at the raw-check level in every one of the 4 runs even though it did not produce a workbook-case FAIL (TC-033-011 was pre-loosened to absorb the TRACE/405 half of it), and (b) the three sheet-vs-code conflicts the audit already flagged as unresolved, which Schemathesis cannot adjudicate.

## Unresolved expectations and conflicts

Per `verdicts.json`'s `unresolved_expectations`, all three are **Conflict** status except one **Unclear**:
- TC-033-008 (Conflict, `CF-033-02`): legacy/off-tree categories (e.g. "Boots", "Shirts & Tops") may coexist with the curated Women/Men/Kids/Gear tree with no exclusion logic, conflicting with the sheet's implied "curated tree only" framing. Audit confidence on this is **medium** — code-comment evidence only (`categories.repository.ts:24-29`, `embeddings.service.ts:236-239`), not an independently confirmed live-DB fact.
- TC-033-016 (Conflict, `CF-033-01`): sheet title asserts a BA-confirmed "customer-facing" taxonomy filter; no such filter, visibility column, or admin-write field exists anywhere in code or schema (audit findings #3, confidence high — `categories.repository.ts:17-19`, `prisma\schema.prisma:543-565`, `admin\dto\create-category.dto.ts`/`update-category.dto.ts`).
- TC-033-017 (Conflict, `CF-033-03`): sheet row's title calls this the "category tree"; `GET /categories` is the flat list (`findAll()`); the actual tree is the separate `GET /categories/tree` (`getTree()`) operation (`categories.controller.ts:11-14` vs `:19-22`).
- TC-033-021 (Unclear): exact 500 body shape on an unhandled Prisma/DB failure is not independently confirmed; cannot reliably trigger via a normal HTTP request (no params/body to manipulate).

None of these are FAIL verdicts from this run — they were never executed against live evidence because they are explicitly flagged `needs_other_method`/`BLOCKED` by design (per the pre-run case design, confirmed correct by the independent review). Per the task rules, any eventual FAIL evidence against these would be a "potential defect — clarify first," not a confirmed defect, until the BA/PO clarifies the sheet's intent.

## Cases needing another execution method

From `verdicts.json`'s `needs_other_method` list (10 entries):
- TC-033-006 (sortOrder-then-name ordering) — Manual: needs a fixture with ≥2 categories deliberately out of alphabetical order; not schema-driven, Schemathesis cannot assert ordering semantics.
- TC-033-007 (empty taxonomy returns `[]`) — Manual: needs an empty-DB fixture.
- TC-033-008 (legacy/off-tree category coexistence) — Manual: needs a live-DB legacy-category fixture; also an unresolved conflict (see above).
- TC-033-009 (deleted category no longer appears) — Postman: needs an admin DELETE mutation + before/after GET sequence.
- TC-033-010 (category with listings blocks 409, still appears) — Postman: needs a category-with-listing fixture + admin delete attempt.
- TC-033-014 (429 after 100 req/min) — Postman: needs a burst/load harness, not a single Schemathesis request.
- TC-033-016 (customer-facing filter conflict) — Manual: no filter exists to test; also an unresolved conflict.
- TC-033-017 (tree vs. flat-list naming conflict) — Manual: naming/documentation issue, not a runtime check; also an unresolved conflict.
- TC-033-020 (Home/Explore/Search/Sell/Preferences screens render correctly) — Playwright: UI-rendering assertion, not an API contract check.
- TC-033-021 (unhandled DB failure → 500 shape) — Manual: requires fault injection (e.g. staging DB outage) not available to Schemathesis.

## Could not verify

- Full-body response identity across roles (TC-033-002/003/004 only check `[0].id`, not a full diff) — flagged by the independent case review (`testcases\reviews\EP-033-review.md` finding #6), not strengthened by this run's evidence.
- Response schema conformance for the 200 body against OpenAPI (TC-033-015) — spec declares no schema (`openapi.pretty.json:1215-1219`); the check is structurally unable to run, not merely unexecuted.
- Whether legacy/off-tree categories exist in the current production database right now (TC-033-008) — audit confidence is medium, code-comment evidence only, not a live DB query; this run's fixtures contain zero `/categories` entries so Schemathesis could not probe this either.
- Exact 500 body shape on an unhandled Prisma/DB failure (TC-033-021) — no fault-injection capability in this run.
- Whether the "Flow 1, 2, 6" usage note maps to any specific legend — the audit found no flow-numbering legend in `docs\`, `qa-knowledge\`, or either repo; not re-attempted here as it is outside Schemathesis evidence scope.
