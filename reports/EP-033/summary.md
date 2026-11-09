# EP-033 - GET /categories - Schemathesis summary
Run: `D:\API Testing\API_Automation\schemathesis\results\2026-11-09_1241_EP-033_user` | Env: `https://api-qa.redspur.com/api` | Role: user (regular authenticated user — per run-folder suffix `_user`) | Date: 2026-11-09

## Result at a glance
| Phase | Pass | Fail | Skip |
|---|---|---|---|
| examples | 0 | 0 | 1 (no examples in schema — op has no params) |
| coverage | 36 | 2 | 0 |
| fuzzing | 13 | 0 | 0 |

38 checks passed, 2 failed, 1 distinct root cause area (`unsupported_method`, 2 sub-findings). No `response_schema_conformance` / `content_type_conformance` / `response_headers_conformance` / `negative_data_rejection` / `positive_data_acceptance` failures.

## Coverage gaps
1. **2xx did occur but conformance checks on it are vacuous.** Cases `vgyhXb` (coverage, 200) and `JmF5dg` (fuzzing, 200) both returned HTTP 200 (results_detail.csv rows 21-34, 41-54) and `response_schema_conformance`, `content_type_conformance`, `response_headers_conformance` all PASS — but the spec's `200` response for this operation is `{"description":""}` with **no `content`/schema at all** (confirmed in `schemathesis\spec\openapi.json`: `"/categories":{"get":{"operationId":"CategoriesController_findAll",...,"responses":{"200":{"description":""}},"tags":["Categories"]}}`). This matches the explicit spec-bug rule: these three checks passed vacuously because there is nothing to validate against, not because the response is correct. **Fix: add `@ApiOkResponse({ type: <CategoryDto> })` (and an array wrapper if it returns `Category[]`) in `apps\api\src\categories\categories.controller.ts:10-13`.** Until that exists, Schemathesis can never surface extra/missing/wrong-type field findings for this endpoint.
2. **`negative_data_rejection` / `positive_data_acceptance` pass trivially (1 case each, both PASS).** The operation declares `"parameters":[]` in the spec, so there is nothing for Schemathesis to mutate or validate — these two checks are no-ops here, not evidence of correct validation.
3. **Role coverage:** run used the `user` role only. `categories.controller.ts` has no `@UseGuards`/`@Roles`/`@Public` decorators at all (lines 1-29) — i.e., the code itself appears to have no RBAC on this route, so anonymous and admin callers should behave identically. However that equivalence was not actually exercised in this run (no anonymous/admin run exists), so it is inferred from code, not proven by a test.
4. **fixtures.json** (`D:\API Testing\API_Automation\schemathesis\fixtures.json`) has no entry for `GET /categories` — there are no path/query params for this operation, so no fixture ids were needed or used.
5. **Business-intent gap (not a Schemathesis finding):** the sheet description asks to verify the tree "reflects only categories intended to be customer-facing, per taxonomy rules." The `Category` Prisma model (`apps\Redspur_Backend... prisma\schema.prisma:543-565`) has **no field** distinguishing customer-facing vs internal/admin-only categories, and `CategoriesRepository.findAll()` (`apps\api\src\categories\categories.repository.ts:17-19`) issues `prisma.category.findMany({ orderBy: [...] })` with **no `where` clause at all** — every category row is returned. Whether the QA data set happens to contain only customer-facing rows is a data/business question, not an HTTP-schema one, and is outside what Schemathesis can detect (there's also no schema to diff against per gap #1). Flagged for manual BA/product review, not filed as a bug here.
6. **No audit file exists** for EP-033 at `audits\EP-033.md` — this report uses only the Schemathesis run and the sheet row, as instructed.

## Fields / params to remove or fix (combined: Schemathesis + audit)
No audit file exists for EP-033, so this is Schemathesis-only. No field/param-level (Bucket A) findings are possible for this endpoint at all: it declares zero request parameters, and its 200 response has no schema in the spec (see Coverage gap #1), so there is nothing for `response_schema_conformance`/`negative_data_rejection`/`positive_data_acceptance` to compare against.

| # | Item | Kind | Source | Evidence | Recommendation | Confidence |
|---|---|---|---|---|---|---|
| 1 | `200` response has no `content`/schema | response | spec coverage gap (openapi.json) | `schemathesis\spec\openapi.json` (`"/categories":{"get":{...,"responses":{"200":{"description":""}}}}`); `apps\api\src\categories\categories.controller.ts:10-13` (no `@ApiOkResponse`) | FIX SPEC — add `@ApiOkResponse({ type: ... })` so future runs can actually check fields | High |

## Other failures (see bug report)
- BUG-EP033-01 - TRACE returns 405 without required `Allow` header - low
- BUG-EP033-02 - QUERY returns 404 instead of 405 for an unmapped method - low

## Could not verify
- Whether the returned category list is correctly restricted to "customer-facing" categories per BA taxonomy rules (sheet's stated test intent) — no schema/flag exists to check this via HTTP, and the repository query applies no filter at all (`categories.repository.ts:17-19`). Needs manual BA/QA content review of the QA category table, not an automated fix.
- Whether anonymous or admin roles behave differently — not run in this session; code inspection suggests no (no guards found), but not empirically tested.
- Field-level correctness of the actual category objects returned (names, slugs, order, nesting) — blocked entirely by Coverage gap #1 (no response schema to validate against).
