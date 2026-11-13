# EP-038 - Bug report

No application defect is confirmed. Two spec/docs bugs and three "potential defect - clarify first" items follow, plus a test-design note. Nothing was filed in Linear.

### BUG-EP038-01 - OpenAPI spec documents no 404 and no 200 schema for GET /listings/{id}
- Severity: medium | Type: Spec/docs bug
- Roles: user, admin, anon. Runs: RUN-20261112-225526-EP-038-user, RUN-20261112-225607-EP-038-admin, RUN-20261112-225642-EP-038-anon.
- Cases: TC-038-034, 035, 037, 038 failed; TC-038-008 also failed on 200/404 requests (link to ST103 inferred); TC-038-003, 006, 010 BLOCKED.
- Steps: `curl -s -o NUL -w "%{http_code}" https://<host>/listings/<nonexistent-id>` returns 404.
- Expected: a 404 is documented and the 200 has a schema (audit finding 9). Actual: spec has only `"200":{"description":""}`.
- Check: ST103 status_code_conformance, 4 failing requests in each of the user, admin and anon runs (tally).
- Suspected location: `listings.controller.ts:373-378` (`findById`) has no `@ApiResponse`/`@ApiNotFoundResponse`/`@ApiOkResponse({type})`. Fix type: spec/decorator.
- Impact: contract tests and generated clients cannot validate the listing detail.

### BUG-EP038-02 - OpenAPI spec declares no auth/security for an optional-auth route
- Severity: low | Type: Spec/docs bug (TC-038-067, Conflict)
- Evidence: RUN-20261112-225642-EP-038-anon; guard at `optional-jwt-auth.guard.ts:1-17`; no `security` anywhere in the spec.
- Expected: spec states a Bearer token is optional (a `pending_approval` listing returns 404 unless caller is owner/admin, `listings.service.ts:784-788`). Actual: spec silent.
- Impact: integrators cannot tell that owner/admin tokens change the response.

### BUG-EP038-03 - Draft, rejected and inactive listings are readable by anonymous callers
- Severity: medium | Type: Potential defect - requirement unclear (clarify first)
- Run: RUN-20261112-225642-EP-038-anon. Cases TC-038-013 (draft), 016 (inactive), 023 (rejected) returned 200.
- Expected per sheet title: 404 for anyone except owner/admin. Actual: 200 with the full DTO; code gates only `pending_approval` (`listings.service.ts:60,786`), asserted by `listings.service.spec.ts:965-972`, documented in `docs/domain.md:70` (BRI-44).
- Suggested: PO/QA decides - change title/expectations to match BRI-44, or raise a product ticket to gate these states (behaviour change).
- Impact: draft seller identity, price and photos exposed to unauthenticated callers. Related: review High finding 2; `ResumeDraft.tsx:31,39` relies on draft staying ungated.

### BUG-EP038-04 - Soft-deleted listing returns 404 for owner and admin
- Severity: medium | Type: Potential defect - requirement unclear
- Cases: TC-038-027, 047, 061, 062, 063. No soft-deleted fixture exists, so none was executed.
- Expected per sheet: "removed" listing visible to owner/admin. Per code: 404 for everyone (`listings.repository.ts:692-704`, `listing.constants.ts:60-68`, `docs/domain.md:75`). No `removed` status exists (`schema.prisma:36-45`). Admin web page uses this route (`apps\web\src\app\admin\listings\[id]\page.tsx:61`).
- Do not file as an app bug until the PO clarifies and a fixture exists.

### BUG-EP038-05 - Unsupported-method requests (ST204)
- Severity: low | Type: Potential defect - requirement unclear
- Runs: user, admin, anon; 1 failing request per role (tally). Cases TC-038-001, 004, 007, 036: single 405 each. Review finding 17 calls the TRACE check "likely noise"; the 405 body is nginx's. Confirm the intended behaviour in `evidence.json` before filing.

### BUG-EP038-06 - Test-design holes (not a product defect)
- Independent review verdict REWORK (4 High findings, see summary.md). TC-038-025, 053, 057, 060 have no matching scenario executed.
- Do not treat PASS/FAIL on TC-038-013, 016, 023, 026, 047, 059, 061, 062, 063, 068 as final until the case design is corrected.

## BLOCKED and NOT RUN scope
- Soft-deleted fixture: TC-038-024, 047, 061, 062, 063.
- Spec 200 schema: TC-038-003, 006, 010.
- No matching scenario executed: TC-038-025, 053, 057, 060.
- Other execution methods: list in summary.md.
