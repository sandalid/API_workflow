# EP-109 - GET /sellers/me - evidence summary

Runs:

| run id | role | auth | status | spec version | errors |
|---|---|---|---|---|---|
| RUN-20261109-202832-EP-109-user | user | ok (otp bootstrap) | completed | 1.0 (sha256 8c58e57f...) | 0 |
| RUN-20261109-202850-EP-109-admin | admin | ok (password bootstrap) | completed | 1.0 (sha256 8c58e57f...) | 0 |
| RUN-20261109-202907-EP-109-anon | anon | anonymous-explicit | completed | 1.0 (sha256 8c58e57f...) | 0 |

All three runs share the same spec hash and the same fixture snapshot (`fixtures.snapshot.json`, sha256 887cedbf...); all three completed with `exit_code: 1` but `status: completed` and `execution_errors: []` — the non-zero exit is from Schemathesis checks failing (ST204/ST103), not from a harness crash. No auth failures, no execution errors on any run. Evidence is complete for everything Schemathesis is capable of exercising on this endpoint.

## Verdict counts (PASS 6 / FAIL 1 / BLOCKED 1 / NOT RUN 0) and what they do and do not prove

- **PASS (6): TC-109-001, 002, 004, 008, 012, 015.**
  - TC-109-001 (active seller, 200) — `RUN-...-user`, requests `[GI6z0E, n7KQhf, CZ24nl]`, status 200. Assertions checked and satisfied: `body.shopName exists`, `body.isSeller == true`, **and explicitly `body.suspended absent`, `body.status absent`** (verdicts.json, TC-109-001). This PASS proves the happy-path 200 body shape matches code, and confirms (not just asserts) that no `suspended`/`status` field is present on a live response.
  - TC-109-002 (non-seller USER → 403) — `RUN-...-admin` (admin JWT is not a seller, so it exercises the 403 path), status 403, body `{"message":"Insufficient permissions."}` matched exactly.
  - TC-109-004 (no token → 401) — `RUN-...-anon`, status 401.
  - TC-109-008 (unexpected query params ignored) — `RUN-...-user`, status 200.
  - TC-109-012 (no `id` key in response) — `RUN-...-user`, status 200, `body.id absent` confirmed.
  - TC-109-015 (anon "all other" checks: not_a_server_error, max_response_time) — `RUN-...-anon`, status 401, both checks satisfied.
  - These PASSes prove: status-code + specific-field/body-content assertions for the happy path, the non-seller 403, the no-token 401, and absence of `id`/`suspended`/`status`. They do **not** prove anything about a suspended account's behavior (Schemathesis has no suspend-fixture capability here — see "Cases needing another execution method").

- **FAIL (1): TC-109-014** — unsupported-method check, run `RUN-20261109-202907-EP-109-anon`, case `EZ1RUg` (TRACE). Status 405 (expected), but the `allow` header assertion was **violated**: "header allow present -> absent" (verdicts.json TC-109-014; raw evidence `RUN-...-anon/evidence.json:19-52`). The identical defect also fired under `user` (case `a6UFvQ`) and `admin` (case `YfpPMp`) roles as new, evidence-backed findings not mapped to an existing TC — see "New evidence-backed cases" below.

- **BLOCKED (1): TC-109-013** — `response_schema_conformance` check could not be performed: "spec declares no schema for GET /sellers/me -> 200... 'response_schema_conformance' passed vacuously" (verdicts.json TC-109-013). This is a coverage gap, not a pass — Schemathesis has nothing to validate the 200 body shape against because the OpenAPI spec for this operation has no `content`/`schema` key at all (confirmed in audit EP-109.md:64-66, operation body quoted verbatim). The only reason field-level content was checked at all is because TC-109-001/008/012 hard-coded specific field assertions independently of the (absent) spec schema.

- **NOT RUN (partial): 0** — no case was left half-checked; every workbook case is either a recorded verdict, in `needs_other_method`, or in `unresolved_expectations`.

## Evidence gaps and execution errors

- No execution errors in any of the three `run.json` manifests (`execution_errors: []` across user/admin/anon).
- The only structural evidence gap is TC-109-013 (BLOCKED): no response schema in the spec means `response_schema_conformance` cannot meaningfully run for the 200 response.
- Undocumented-status-code findings (ST103) were observed in both the admin and anon runs:
  - Admin run: `status_code_conformance` failure, code ST103, "Received: 403 Documented: 200" (`RUN-...-admin/evidence.json:288-291`).
  - Anon run: `status_code_conformance` failure, code ST103, "Received: 401 Documented: 200" (`RUN-...-anon/evidence.json:279-282`).
  - These are **not** treated as new/unmatched findings in `verdicts.json` (they do not appear in `unmatched_failures`) — the evidence tool folded them into the already-known spec gap (audit Finding #7: "OpenAPI spec documents no schema for 200, and no 401/403/404 at all"). They are real contract-conformance failures against the spec, but they describe correct, intentional application behavior (403 for non-sellers, 401 for anonymous callers) against an incomplete spec, not an app defect. See "Fields/params to remove or fix" row 3 and audit Source Agreement Matrix rows "Auth requirement on this route" / "401/403/404 documented" (both "Spec-gap").

## Fields / params to remove or fix

| # | Item | Kind | Source | Evidence | Recommendation | Confidence |
|---|---|---|---|---|---|---|
| 1 | `id` field — required/non-nullable on mobile `SellerProfile` type, never sent by backend | Response field (client-contract mismatch) | Audit Finding #4 (`sellersApi.ts:41` vs `sellers.service.ts:500-523`); confirmed live by TC-109-012 PASS, `body.id absent` (verdicts.json, `RUN-...-user`) | TC-109-012 PASS — `body.id absent -> missing` on a live 200 | FIX CODE (mobile): make `id` optional on `SellerProfile`, or FIX CODE (backend): add `id` to the DTO if a consumer actually needs it. Audit found no live reader of `profile.id` off this endpoint (`ShopProfile.tsx:146` reads `.id` from a different endpoint). | high |
| 2 | `suspended`/`status` field — absent from this endpoint's response, present on sibling admin DTOs | Response field (missing, possible contract gap) | Audit Findings #2/#3; TC-109-006 unresolved expectation (verdicts.json `unresolved_expectations`) | TC-109-001 PASS confirms `body.suspended absent`, `body.status absent` on a live 200 (verdicts.json) | Do **not** REMOVE/ADD unilaterally — this is the crux of the sheet-title conflict (TC-109-006). VERIFY WITH PRODUCT/QA FIRST: is the intended design "block before profile" (current, matches `docs/manual-test-cases.md:548-551`) or does product actually want a new "suspended banner on own profile" capability? Only after that decision is FIX SPEC/FIX CODE actionable. | medium (requirement conflict, not yet a confirmed defect) |
| 3 | 200-only documented responses (no 401/403/404/security scheme) | Spec completeness | ST103 (admin 403, anon 401) + audit Finding #7 + Source Agreement Matrix ("Spec-gap" rows) | Admin: `evidence.json:288-291` "Received: 403 Documented: 200"; Anon: `evidence.json:279-282` "Received: 401 Documented: 200" | FIX SPEC — add `401`, `403`, `404` response entries and a `security` scheme (bearer JWT) to the OpenAPI operation for `SellersController_getProfile` | high |
| 4 | Missing `Allow` header on TRACE's 405 response | Response header, RFC 9110 compliance | ST204 `unsupported_method` check; TC-109-014 FAIL + 2 new evidence-backed cases (user, admin) | `RUN-...-user` case `a6UFvQ`; `RUN-...-admin` case `YfpPMp`; `RUN-...-anon` case `EZ1RUg`/TC-109-014 — all three show `405` with no `allow` header; response body is nginx's default error page (`server: nginx/1.28.3`), see "Suspected location" in bug report | FIX CODE/INFRA — add `Allow` header at whichever layer terminates TRACE (appears to be the nginx reverse proxy, not the NestJS app — see Bugs doc) | high |
| 5 | Unsupported method `QUERY` returns 404 instead of 405 | Response status, RFC 9110-adjacent | ST204 `unsupported_method`; 3 new evidence-backed cases (user, admin, anon) | `RUN-...-user` case `Lkv9Aq` (404); `RUN-...-admin` case `ncC0Mq` (404); `RUN-...-anon` case `49nap5` (404), body `"Cannot QUERY /sellers/me"`, `x-powered-by: Express` | This is Express's/NestJS's default unmatched-route 404 (confirmed framework-wide default — `main.ts` has no custom 404/405 handler). FIX CODE (platform-wide, not EP-109-specific) if RFC-strict 405 behavior is desired, otherwise FIX SPEC/accept as known platform behavior. Scope is backend-wide, not this endpoint alone — do not fix only here. | medium |

## Defects

See Bug Report below (`===== BUGS =====`). In summary: one genuine, reproducible defect (missing `Allow` header on 405), one adjacent framework-wide pattern (QUERY → 404 instead of 405), and the ST103 undocumented-status-code findings which are spec-gaps, not app bugs — the app's 403/401 behavior for admin/anon callers is correct and intentional per the audit's role matrix (EP-109.md "Test design inputs" §a).

## Unresolved expectations and conflicts

- **TC-109-006** (central conflict, also carried in `unresolved_expectations` in verdicts.json): "Sheet-title-literal scenario: 'a suspended seller's own profile view clearly reflects the suspended status' — cannot be given a trustworthy expected result as written." This is **not** executable by Schemathesis and is **not** a code defect. Per the audit's Source Agreement Matrix (EP-109.md lines 164-172) and Finding #1:
  - `JwtStrategy.validate` (`jwt.strategy.ts:42`) throws `401 Account suspended.` for any suspended account **before** `SellersController.getProfile` ever runs — so a suspended seller structurally cannot reach a 200 from this endpoint to inspect anything.
  - Even hypothetically bypassing that gate, the response DTO (`sellers.service.ts:500-523`) has no `suspended`/`status` field to "clearly reflect" — unlike the admin-facing `getAllSellers`/`getSellerByIdForAdmin` (`sellers.service.ts:1272-1273`, `:1311-1312`), which do carry such a field.
  - The team's own `docs/manual-test-cases.md:544-551` documents the intended behavior as a **login-time block**, not a profile-view state — agreeing with the shipped code, but contradicting the sheet row's framing.
  - **This is a requirement/spec conflict, not an app bug.** It needs product/QA to decide between two mutually exclusive interpretations: (a) rewrite the sheet row to match the actual login-blocking design, or (b) treat this as a net-new feature request (let a suspended seller authenticate and see a "Suspended" banner on `/sellers/me`). No FAIL verdict should be filed against this endpoint for TC-109-006 until that decision is made — there is no code path that could produce the sheet's literal expectation, so a FAIL here would misattribute a product-requirements question as an engineering defect.

## Cases needing another execution method

Per `verdicts.json` → `needs_other_method` (7 cases, all flagged "not a Schemathesis case" because they require fixture/account state manipulation Schemathesis cannot drive):

| TC | Scenario | Suggested method |
|---|---|---|
| TC-109-003 | Non-seller USER → 403 (role-fixture dependent variant) | Manual |
| TC-109-005 | Pre-existing valid JWT; account suspended mid-session via admin action; replay old token → 401 "Account suspended.", no profile body | Manual (requires: issue JWT, then admin-suspend, then replay) |
| TC-109-006 | Sheet-title-literal scenario (see Unresolved expectations above) | Manual — but blocked on product/QA clarification, not just execution method |
| TC-109-007 | No cross-account access vector exists (no `:id` param) | Manual (documents absence of IDOR surface, not a test to run) |
| TC-109-009 | Malformed/expired/tampered JWT → 401, no 500/leak | Postman |
| TC-109-010 | Session revoked via `sid` check, retry with old token → 401 distinct from suspension | Manual |
| TC-109-011 | Seller mid-onboarding (`sellerProfile: null`) → 404 | Manual |

## Could not verify

- **Response-schema conformance for 200** (TC-109-013) — spec has no schema; Schemathesis cannot assert body shape against a contract that doesn't exist (only the hand-picked field assertions in TC-109-001/008/012 cover this, and only for the exact fields someone thought to assert).
- **Whether the suspended-seller 401 reaches any user-visible "suspended" text in either client** — out of Schemathesis's scope entirely (client-side rendering); audit flags this as "Could not verify" too (EP-109.md lines 91-95), not fully traced through `OtpEntry.tsx`/`UnifiedLogin.tsx`.
- **Root cause/owning layer for the missing `Allow` header and the QUERY→404 behavior** — evidence strongly suggests nginx (TRACE: `server: nginx/1.28.3`, nginx's own HTML error page, `evidence.json:19-33`) and Express's default router (QUERY: `x-powered-by: Express`, `"Cannot QUERY /sellers/me"`, `evidence.json:93-110`) respectively, confirmed by the absence of any custom handler in `main.ts`, but the actual nginx configuration file was not available to inspect directly.
