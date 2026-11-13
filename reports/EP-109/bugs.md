# EP-109 - Bug report

### BUG-EP109-01 - TRACE to /sellers/me returns 405 without a required `Allow` header (RFC 9110 violation)

- **Severity:** Low (spec/protocol-compliance gap; no data exposure, no auth bypass, no 5xx) | **Type:** Infrastructure (evidence points to the reverse-proxy/web-server layer, not application code)
- **Endpoint / env / role / run id(s) / case ids:** `GET /sellers/me` (method TRACE), `api-qa.redspur.com`. Reproduced identically across all three roles:
  - user: `RUN-20261109-202832-EP-109-user`, case `a6UFvQ`
  - admin: `RUN-20261109-202850-EP-109-admin`, case `YfpPMp`
  - anon: `RUN-20261109-202907-EP-109-anon`, case `EZ1RUg` (= TC-109-014, verdict FAIL)
- **Steps to reproduce:**
  ```
  curl -i -X TRACE https://api-qa.redspur.com/api/sellers/me
  ```
  (no auth header needed to reproduce — the anon-role case `EZ1RUg` had `has_auth: false` and still got 405; `st replay EZ1RUg` / `st replay a6UFvQ` / `st replay YfpPMp` against the respective run directories)
- **Expected:** RFC 9110 §15.5.6 requires a `405 Method Not Allowed` response to include an `Allow` header listing the methods that are supported on the target resource. Schemathesis's `unsupported_method` check (ST204) encodes this requirement.
- **Actual:** Status 405 returned, `Allow` header absent in all three runs. Response body/headers (anon run, `RUN-...-anon/evidence.json:19-33`):
  ```
  server: nginx/1.28.3 (Ubuntu)
  content-type: text/html
  <html><head><title>405 Not Allowed</title></head><body><center><h1>405 Not Allowed</h1></center>
  <hr><center>nginx/1.28.3 (Ubuntu)</center></body></html>
  ```
  The `server: nginx/1.28.3` header and nginx's stock HTML error page (not a NestJS JSON error body) indicate this 405 is generated at the **reverse-proxy layer**, before the request reaches the NestJS application — TRACE is very commonly blocked by web servers/proxies for security reasons (HTTP TRACE / XST attack mitigation), independent of application routing.
- **Check/code:** `unsupported_method` / ST204, verdict TC-109-014 = FAIL (verdicts.json); identical finding also surfaced as new evidence-backed cases for `user` and `admin` roles (not mapped to an existing workbook TC).
- **Occurrences:** 3 (one per role: user, admin, anon) — same root cause, same proxy layer.
- **Workbook TC IDs affected:** TC-109-014 (FAIL); the user/admin role occurrences are new findings not previously in the workbook.
- **Suspected location and suggested fix:** Not inside `apps/api/src` — `sellers.controller.ts:128-133` has no TRACE handling because NestJS's `@Controller`/`@Get` decorators never register TRACE at all; `main.ts` (checked lines 1-32) configures no custom 404/405 handler. The 405 + missing header is produced upstream (nginx or equivalent reverse proxy in front of `api-qa.redspur.com`). Suggested fix: add an `Allow` header to the proxy's method-not-allowed response (or, if TRACE must remain hard-blocked for security, configure the proxy to still emit a minimal `Allow: GET` header alongside the 405/403). This is infrastructure config, not an `apps/api` code change.
- **Business impact:** Low — TRACE is not a method any client uses against this endpoint; this is a hygiene/compliance gap that could be flagged by automated API-conformance scanners or security audits, not a functional defect affecting real traffic.

### BUG-EP109-02 - Unsupported method QUERY returns 404 instead of 405 (framework-wide, not EP-109-specific)

- **Severity:** Low | **Type:** Infrastructure/framework-default (scope is backend-wide, not this endpoint)
- **Endpoint / env / role / run id(s) / case ids:**
  - user: `RUN-20261109-202832-EP-109-user`, case `Lkv9Aq`
  - admin: `RUN-20261109-202850-EP-109-admin`, case `ncC0Mq`
  - anon: `RUN-20261109-202907-EP-109-anon`, case `49nap5`
- **Steps to reproduce:**
  ```
  curl -i -X QUERY https://api-qa.redspur.com/api/sellers/me
  ```
  (`st replay 49nap5` against `RUN-20261109-202907-EP-109-anon`)
- **Expected:** Per ST204, a method not listed in the OpenAPI spec for this path should return `405 Method Not Allowed` (ideally with `Allow`).
- **Actual:** Status `404`, body `{"success":false,"statusCode":404,"message":"Cannot QUERY /sellers/me","error":"Not Found"}`, header `x-powered-by: Express` (anon run, `evidence.json:93-110`). This is Express's/NestJS's default unmatched-route handler firing for an unrecognized HTTP verb — it treats "no route registered for this method+path combination" the same as "no route at all," producing a 404 rather than distinguishing "path exists, method doesn't" (405). `main.ts` has no custom routing middleware that would change this default.
- **Check/code:** `unsupported_method` / ST204, 3 new evidence-backed findings (not mapped to an existing workbook TC, one per role, identical root cause).
- **Occurrences:** 3 (user, admin, anon) — confirmed same across all roles, consistent with this being a route-table-level default rather than anything role- or auth-dependent.
- **Workbook TC IDs affected:** None directly (new finding); related in spirit to TC-109-014.
- **Suspected location and suggested fix:** Framework-default behavior of the NestJS/Express router — not something to fix inside `sellers.controller.ts`. If RFC-strict 405 behavior is wanted, it would require a global middleware/interceptor that, for a matched path with no matched method, emits 405+`Allow` instead of falling through to Express's catch-all 404 — this is a platform-wide change (every endpoint in the API would behave the same way), not something to scope to EP-109 alone.
- **Business impact:** Low — QUERY is an unusual/emerging HTTP method not used by either client (mobile or web, per audit's call-site inventory); this is a conformance nicety, not a functional risk.

### Non-bug item: TC-109-006 (sheet-title conflict) — explicitly NOT filed as a defect

Per task instructions, this is called out here for completeness but is **not** a bug:

- **Type:** Potential defect — requirement unclear (per severity taxonomy, explicitly excluded from "App bug"/"Infrastructure" categories)
- **Why no bug is filed:** The sheet row's premise — "a suspended seller's own profile view clearly reflects the suspended status" — requires a 200 response containing a status indicator for a suspended account. The shipped code makes this combination of states unreachable: `JwtStrategy.validate` (`jwt.strategy.ts:42`) 401s every request from a suspended account before `SellersController.getProfile` executes, and even if that gate were bypassed, the response DTO (`sellers.service.ts:500-523`) has no `suspended`/`status` field to show. There is no single line of code whose change would make the sheet's literal scenario pass without a product decision first — this is two possible, mutually exclusive designs (login-time block vs. a new profile-view "Suspended" banner), and choosing between them is a product/requirements decision, not an engineering fix.
- **What would need to happen first:** Product/QA must clarify whether the sheet row should be rewritten to test the actual (login-blocking) behavior, or whether a new capability (let a suspended seller log in and see a status banner) should be scoped as a feature request. Only after that clarification could TC-109-006 be re-run with a trustworthy expected result, or closed as "sheet row incorrect."
- **Evidence:** `verdicts.json` → `unresolved_expectations` → TC-109-006, "CF-109-01: expected behaviour not clarified"; audit EP-109.md Source Agreement Matrix (lines 164-172), Finding #1 (`jwt.strategy.ts:42`), Finding #3 (`sellers.service.ts:1272-1273`/`:1311-1312` contrast).

Relevant paths referenced in this analysis:
- `D:\API_workflow\audits\EP-109.md`
- `D:\API_workflow\schemathesis\results\RUN-20261109-202832-EP-109-user\run.json`, `verdicts.json`, `verdicts.md`, `evidence.json`
- `D:\API_workflow\schemathesis\results\RUN-20261109-202850-EP-109-admin\run.json`, `evidence.json`
- `D:\API_workflow\schemathesis\results\RUN-20261109-202907-EP-109-anon\run.json`, `evidence.json`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\sellers\sellers.controller.ts:48-133`
- `D:\Redspur_Backend\redspur-droplight\apps\api\src\main.ts:1-32`
