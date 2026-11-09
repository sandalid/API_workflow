# EP-032 - Bug report

### BUG-EP032-01 - TRACE on /brands returns 405 without the RFC 9110-required Allow header
- **Severity:** Low/Medium (spec-compliance/RFC-conformance gap, not a security or data-exposure issue) | **Type:** Infrastructure (framework-level routing behavior, not endpoint-specific code)
- **Endpoint / env / role / run id(s) / case ids:** `GET /brands`, `api-qa.redspur.com`, roles anon/user/admin:
  - anon: `RUN-20261109-184435-EP-032-anon`, case `MTJIBU` (TC-032-016, FAIL)
  - user: `RUN-20261109-184340-EP-032-user`, case `lNeSXX` (new evidence-backed case, no prior TC)
  - admin: `RUN-20261109-184418-EP-032-admin`, case `ecA70P` (new evidence-backed case, no prior TC)
- **Steps to reproduce:** `curl -X TRACE https://api-qa.redspur.com/api/brands` (any role, including anonymous). Also: `st replay lNeSXX`, `st replay ecA70P`, `st replay MTJIBU`.
- **Expected:** Per RFC 9110 §15.5.6, a 405 response must include an `Allow` header listing the methods actually supported on the resource (here: `GET`). Schemathesis's `unsupported_method` check enforces this.
- **Actual:** Returns `405 Method Not Allowed` but with the `Allow` header absent in all three roles.
- **Check/code, occurrences, workbook TC IDs affected:** `unsupported_method` (ST204-family), 3 occurrences (anon/user/admin), TC-032-016 plus the two new evidence-backed cases flagged by `evidence.py`.
- **Suspected location and fix:** No endpoint-specific code sets this — `brands.controller.ts:6-14` only registers `@Get()`; there is no custom 405 handler. The gap is in the global exception/routing layer: `AllExceptionsFilter` (`apps\api\src\common\filters\all-exceptions.filter.ts:19-53`) re-shapes `HttpException` responses but never inspects/sets headers, and no middleware populates `Allow`. Fix should be platform-wide (e.g. a Nest `NotFoundException`/`MethodNotAllowedException` interceptor or Express router config that computes the allowed verbs per matched path and sets the header), not a per-endpoint patch — expect the same gap on every controller in the app.
- **Business impact:** Low direct business impact (TRACE is not used by any real client); matters for API-contract/RFC-conformance audits and any automated tooling that relies on `Allow` headers for capability discovery.

### BUG-EP032-02 - Non-standard HTTP method (QUERY) returns 404 instead of 405
- **Severity:** Low (spec-compliance gap, consistent with a known cross-endpoint pattern) | **Type:** Infrastructure (framework-level, same root cause suspected as EP-033)
- **Endpoint / env / role / run id(s) / case ids:**
  - user: `RUN-20261109-184340-EP-032-user`, case `JguVDe`, status 404
  - admin: `RUN-20261109-184418-EP-032-admin`, case `tqDMYh`, status 404
  - anon: `RUN-20261109-184435-EP-032-anon`, case `9jSfI4`, status 404
  (all three raw Schemathesis findings, check `unsupported_method`/ST204; none matched to an existing workbook TC.)
- **Steps to reproduce:** `curl -X QUERY https://api-qa.redspur.com/api/brands`. `st replay JguVDe` / `tqDMYh` / `9jSfI4`.
- **Expected:** Since `/brands` only supports `GET`, an unsupported method should return `405 Method Not Allowed` (with `Allow` header — see BUG-EP032-01), per the same `unsupported_method` check semantics applied to TRACE.
- **Actual:** Returns `404 Not Found` instead of `405` for the `QUERY` verb, across all three roles identically.
- **Check/code, occurrences, workbook TC IDs affected:** `unsupported_method` (ST204), 3 occurrences, no existing TC — recommend adding a new workbook test case for this pattern.
- **Suspected location and fix:** Same framework-level routing layer as BUG-EP032-01 — `brands.controller.ts` registers only `GET`; Nest's router appears to treat `QUERY` (a newer/non-standard HTTP verb) as simply unmatched (→ its default `NotFoundException`, caught by `AllExceptionsFilter` at `apps\api\src\common\filters\all-exceptions.filter.ts:30-39`) rather than recognizing the path exists under a different verb. Same spec-gap pattern already seen on EP-033 — likely a single shared platform fix (verb-allowlist-aware 405 handling) rather than per-endpoint fixes.
- **Business impact:** Low; no real client issues `QUERY` requests. Relevant to API-contract correctness and any automated conformance scanning across the whole API surface.

### BUG-EP032-03 - Potential defect: response ordering contradicts app/doc assumption (requirement unclear — clarify first)
- **Severity:** Potential defect - requirement unclear (not filed as a confirmed app/code bug) | **Type:** Potential defect - requirement unclear
- **Endpoint / env / role:** `GET /brands`, all roles (public, unauthenticated endpoint)
- **Not evidence from a Schemathesis FAIL** — carried from `unresolved_expectations` (TC-032-007, TC-032-008, both status "Conflict") and audit `CF-032-01`/`CF-032-02`, not from an ST/TC FAIL verdict. Flagging per instructions that a requirement conflict must be clarified before any FAIL claim would be trustworthy.
- **Steps to reproduce:** `GET /brands` with ≥7 seeded brands whose insertion order differs from alphabetical order; compare returned order to `docs\features\brand-drill-down.md` expectation.
- **Expected (per doc/app code comments):** `brand-drill-down.md:16`, `Explore.tsx:52-55` ("in the admin-configured order the API already returns them in — not alphabetical"), `BrandListing.tsx:26-29` ("`GET /brands` returns the admin's own insertion order") — all assume admin-curated/insertion order.
- **Actual (per code):** `brands.repository.ts:14` — `orderBy: { name: 'asc' }`, strictly alphabetical. Additionally, `prisma\schema.prisma:514-521` confirms the `Brand` model has **no `sortOrder`/order column whatsoever** to back the doc's "admin-configured order" premise even if the sort were changed; the admin-only brand read (`admin.repository.ts:432-433`) also hard-sorts alphabetically.
- **Check/code, occurrences, workbook TC IDs affected:** TC-032-007, TC-032-008 (both Conflict status, `needs_other_method`: Manual and Playwright respectively — not Schemathesis-executable).
- **Suspected location and fix:** `brands.repository.ts:14` (sort) and `prisma\schema.prisma:514-521` (missing order column) are the two places that would need to change if product confirms the doc's intent is correct; alternatively `docs\features\brand-drill-down.md:16` and the two app code comments would need correcting if alphabetical is actually intended. **Do not change code or spec until product/PO confirms which side is right.**
- **Business impact:** If the doc's intent is correct, the guest Explore "Shop by brand" taster rail is silently showing the wrong (alphabetical-only) brands instead of admin-curated ones, affecting discovery/merchandising on a guest-facing screen across 8+ mobile call sites. If the code's alphabetical behavior is actually intended, the doc and app code comments are stale and should be corrected instead.

---

**Relevant file paths for reference:**
- `D:\API Testing\API_Automation\schemathesis\results\RUN-20261109-184340-EP-032-user\verdicts.json`
- `D:\API Testing\API_Automation\schemathesis\results\RUN-20261109-184340-EP-032-user\verdicts.md`
- `D:\API Testing\API_Automation\audits\EP-032.md`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\brands\brands.controller.ts`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\brands\brands.service.ts`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\brands\brands.repository.ts`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\common\filters\all-exceptions.filter.ts`
- `D:\Redspur_Backend\redspur-droplight\apps\api\prisma\schema.prisma` (lines 514-521, `Brand` model)
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\main.ts` (lines 20-52, global filters/prefix)
