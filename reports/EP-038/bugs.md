# EP-038 - Bug report

### BUG-EP038-01 - TRACE/unsupported-method 405 response missing required `Allow` header
- **Severity:** Low (protocol-compliance gap, not a security/data issue) | **Type:** App bug (framework-level)
- **Endpoint:** `GET /listings/:id` (route also responds to unsupported methods at the same path) | **env:** api-qa.redspur.com | **role:** user, admin, anon | **run ids:** RUN-20261109-150351-EP-038-user, RUN-20261109-150440-EP-038-admin, RUN-20261109-150516-EP-038-anon
- **Case ids:** TC-038-001 (user), TC-038-004 (admin), TC-038-007 (anon), TC-038-036 (anon, spec-level duplicate check)
- **Steps to reproduce:** `st replay AD4MqV` (user, run RUN-20261109-150351-EP-038-user), `st replay Uns0UZ` (admin), `st replay hWVOUz` (anon) — each sends an unsupported HTTP method (e.g. TRACE) to `/listings/{id}`.
- **Expected:** HTTP 405 response includes an `Allow` header listing the supported methods (RFC 7231 §6.5.5; ST204 check).
- **Actual:** All four cases return `405` with status matched, but assertion `header allow present -> absent` is **violated** in each (verdicts.json detail identical across all 4 cases: `"header allow present -> absent"`).
- **Check/code:** Schemathesis check `ST204`-style header-presence assertion; occurs consistently across all 3 roles, 4 cases total, 0 exceptions.
- **Workbook TC IDs affected:** TC-038-001, TC-038-004, TC-038-007, TC-038-036.
- **Suspected location:** Nest/Express default 405 handler — no custom `Allow` header is set anywhere around the `@Get(':id')` route at `listings.controller.ts:374-378`; this is a framework-wide default behavior, not specific to this handler's code.
- **Suggested fix:** Add an `Allow` header in the global exception filter / method-not-allowed handler, or confirm with infra whether this is an accepted platform-wide gap (if so, reclassify as Infrastructure).
- **Business impact:** Minor — affects HTTP-protocol-compliance tooling/clients that rely on `Allow` to discover supported methods; no functional or security impact on real app usage of this endpoint.

### BUG-EP038-02 - Spec declares only 200 for `GET /listings/{id}`; live API also returns undocumented 404
- **Severity:** Low/Medium (spec-doc gap) | **Type:** Spec/docs bug
- **Endpoint:** `GET /listings/:id` | **env:** api-qa.redspur.com | **role:** user, admin, anon | **run ids:** all 3
- **Case ids:** TC-038-008 (anon), TC-038-037 (user), TC-038-038 (admin) — ST103 status_code_conformance; TC-038-034 (anon) — direct `SPEC:404-documented` check; TC-038-035 (anon) — direct `SPEC:200-schema` check
- **Steps to reproduce:** `st replay d51O8H` (anon, any nonexistent-id or `pending_approval` case within the 38-request batch) — returns `404`, but the spec's `responses` object for this operation only contains `"200":{"description":""}`.
- **Expected:** Per audit's "Declared Contract," the code legitimately throws 404 for two reasons (nonexistent id at `listings.service.ts:775`, hidden `pending_approval` at `listings.service.ts:786-788`); the spec should document both the 404 case and a schema for the 200 case.
- **Actual:** verdicts.json: `"check status_code_conformance: failure ST103 Received: 404 Documented: 200"` (TC-038-008/037/038); `"spec 1.0: GET /listings/{id} does NOT declare response for 404"` (TC-038-034); `"spec 1.0: GET /listings/{id} does NOT declare schema for 200"` (TC-038-035).
- **Check/code:** ST103 (status_code_conformance), direct spec-declaration checks; 5 cases total across all 3 roles, consistent spec-wide finding (audit Finding #9: "spec-wide pattern, not unique to this endpoint").
- **Workbook TC IDs affected:** TC-038-008, TC-038-034, TC-038-035, TC-038-037, TC-038-038.
- **Suspected location:** `schemathesis\spec\openapi.json`, operation `ListingsController_findById`; backend decorators at `listings.controller.ts:373-378` have no `@ApiResponse` decorators to generate a richer spec.
- **Suggested fix:** FIX SPEC — add `@ApiResponse({status:200, schema:...})` and `@ApiResponse({status:404, description:'Listing not found'})` decorators on `findById`, regenerate the OpenAPI doc. This also unblocks the 3 currently-BLOCKED schema-conformance cases (TC-038-003/006/010).
- **Business impact:** Consumers generating clients from this spec, or automated contract tests, cannot detect that a 404 is a normal, expected outcome, nor validate the 200 response shape — pure documentation debt, no runtime defect.

### BUG-EP038-03 - Potential defect, requires clarification - `draft`/`inactive` listings publicly visible, contradicting sheet title
- **Severity:** Potential defect - requirement unclear (not filed as a confirmed defect) | **Type:** Potential defect - requirement unclear
- **Endpoint:** `GET /listings/:id` | **env:** api-qa.redspur.com | **role:** anon | **run id:** RUN-20261109-150516-EP-038-anon
- **Case ids:** TC-038-013 (draft), TC-038-016 (inactive) — both FAIL; also TC-038-023/052 (rejected, BLOCKED — no fixture to actually test) and TC-038-024/047 (soft-deleted, BLOCKED — no fixture) raise the same question for those states
- **Steps to reproduce:** `st replay VnUUDw` (anon, TC-038-013) — GET a listing fixture with `listingStatus: 'draft'` with no Authorization header.
- **Expected (per sheet title):** "Verify a draft or removed listing is not visible to any user other than its owner or an Admin" → 404 for an anonymous/non-owner caller.
- **Actual (per code and test):** `200` with the full DTO (`listingStatus: 'draft'` returned in body) — verdicts.json: `"status 200 expected in [404]"` (violated). Confirmed intentional in backend unit test `listings.service.spec.ts:965-972` (`it.each(['draft','rejected','inactive'])`, asserting these are NOT hidden), and in `listings.service.ts:786` where the only gated status is `HIDDEN_FROM_PUBLIC_STATUS = 'pending_approval'` (`listings.service.ts:45-63`).
- **Check/code:** Business-rule status assertion (`BR:draft-anon`, `BR:inactive-anon`); 2 confirmed FAIL cases (anon), with 2 more states (rejected, soft-deleted) unable to be tested live due to missing fixtures.
- **Workbook TC IDs affected:** TC-038-013, TC-038-016, TC-038-023, TC-038-024, TC-038-047, TC-038-052.
- **Suspected location:** `listings.service.ts:786` (gate logic), `listings.service.ts:45-63` (`HIDDEN_FROM_PUBLIC_STATUS` constant definition) — this is a **behaviour** decision, not a spec/decorator issue; it is also explicitly backed by a product decision reference (BRI-44) in `docs\domain.md:70`, per the audit.
- **Suggested fix:** Do not change code or file as a bug yet. Escalate to QA/PO: either (a) correct the sheet row title to match the shipped BRI-44 behavior ("only pending_approval is hidden; draft/rejected/inactive remain publicly reachable by design"), or (b) raise a product ticket to actually gate `draft`/`rejected`/`inactive` if the row title reflects a genuine, newer requirement that supersedes BRI-44. The soft-delete owner/admin asymmetry (Finding #2, audit) should be resolved in the same conversation since it shares the same sheet-title conflict.
- **Business impact:** If BRI-44 is intentional (most likely, given the explicit unit test coverage), there is no real-world impact — current behavior is as designed. If the sheet title reflects a genuine unmet requirement, unauthenticated users and buyers can currently view full seller identity, pricing, and photos for any draft/rejected/inactive listing, which would be a real visibility/data-exposure gap.

**Unresolved note:** per the audit's Source agreement matrix, TC-038-023/024/047/052 remain BLOCKED (no `rejected`/soft-deleted fixtures were ever provisioned in any of the 3 runs) — these must be re-run with the missing fixture states once provisioned, before this conflict can be fully closed either way for those specific states.

---

**Key file paths referenced:**
- `D:\API Testing\API_Automation\audits\EP-038.md`
- `D:\API Testing\API_Automation\schemathesis\results\RUN-20261109-150351-EP-038-user\verdicts.json` / `verdicts.md`
- `D:\API Testing\API_Automation\schemathesis\results\RUN-20261109-150440-EP-038-admin\` (run.json embedded in verdicts.json "runs" array)
- `D:\API Testing\API_Automation\schemathesis\results\RUN-20261109-150516-EP-038-anon\`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\listings\listings.controller.ts:360-384`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\listings\listings.service.ts:769-791` (findById + visibility gate), `:45-63` (HIDDEN_FROM_PUBLIC_STATUS)
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\listings\listings.repository.ts:689-704` (soft-delete filter)
