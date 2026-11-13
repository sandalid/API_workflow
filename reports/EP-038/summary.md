# EP-038 - GET /listings/:id - evidence summary

Sheet title: "Verify a draft or removed listing is not visible to any user other than its owner or an Admin." Used in App: YES (Flow 3, 18, 26).

No verdict was overridden. Previous results are kept only in `reports\EP-038\results-history.md`; the workbook shows the latest result with the real Actual status / Actual response.

## Runs

| run id | role | auth | status | spec version | errors |
|---|---|---|---|---|---|
| RUN-20261112-225526-EP-038-user | user | ok | completed | 1.0 | 0 |
| RUN-20261112-225607-EP-038-admin | admin | ok | completed | 1.0 | 0 |
| RUN-20261112-225642-EP-038-anon | anon | anonymous-explicit | completed | 1.0 (sha256 8c58e57fc59f) | 0 |

- The tally lists RUN-20261109-195646-EP-038-admin as unreadable (JSONDecodeError). It was skipped and is not evidence.
- No run is flagged as rate-limited.
- Each of the three runs made 45 requests; GET statuses `{'200': 38, '404': 4}` per role.
- Cases needing a soft-deleted resource are BLOCKED: "no fixture resource in state 'soft_deleted'".

## Verdict counts and what they prove

**Workbook after applying the evidence (tally):** 69 cases, BLOCKED 19, FAIL 10, NOT RUN 10, PASS 30; 55 cases have a match spec. (Before apply the tally read PASS 29 / NOT RUN 11; the one change is TC-038-069, NOT RUN -> PASS in the admin run.)

By category (tally before apply): Audit-derived BLOCKED 1, FAIL 1, NOT RUN 6, PASS 1; Business Rule BLOCKED 10, NOT RUN 2, PASS 15; Functional BLOCKED 2, PASS 8; Negative BLOCKED 1, NOT RUN 1, PASS 1; Schema/Contract BLOCKED 2, FAIL 3, PASS 1; Schemathesis BLOCKED 3, FAIL 6, PASS 3; Security/Auth NOT RUN 2.

`verdicts.md` counts (PASS 28 | FAIL 12 | BLOCKED 8 | NOT RUN (partial) 0 | no matching evidence 4) are per-verdict for this run set only: a case appears with the best verdict across roles, and the workbook counts also include earlier results of cases not retested. They are different views, not a sync error.

**Failing requests per role and code (tally):** ST204 (unsupported_method): admin 1, anon 1, user 1. ST103 (status_code_conformance): admin 4, anon 4, user 4.

**What the verdicts prove (verdicts.md):**
- FAIL TC-038-001, 004, 007, 036: one 405 request per role (ST204).
- FAIL TC-038-034, 035: judged on spec 1.0, no request needed.
- FAIL TC-038-008, 037, 038: 42 requests with statuses 200 and 404, consistent with ST103 (404 not documented in the spec; inferred, verdicts.md states no reason).
- FAIL TC-038-013 (draft), 016 (inactive), 023 (rejected) as anon: each returned 200, so those states are visible to anonymous callers. The audit says this matches the code and BRI-44; all three are Conflict/Unclear against the sheet title.
- PASS cases (e.g. TC-038-019, 048, 068: 404 as anon) prove only the observed status and the match spec. A 200 does not prove response content.

## Evidence gaps and execution errors
- Execution errors: 0 in all three runs.
- **No response schema for 200:** TC-038-003, 006, 010 BLOCKED ("response_schema_conformance passed vacuously"). Body shape is not verified by Schemathesis.
- **Soft-deleted fixture missing:** TC-038-024, 047, 061, 062, 063 BLOCKED.
- **No evidence for four cases:** TC-038-025, 053, 057, 060 ("no matching scenario executed").
- Only 200, 404 and the 405 for the unsupported-method request were observed; 400/401/403/5xx were not.
- Not observed: expired/invalid JWT (TC-038-051), cache cross-viewer ordering.
- Cases for another execution method: TC-038-026 to 033, 041, 045, 049, 050, 051, 054, 058, 066, 067.

## Fields / params to remove or fix

| # | Item | Kind | Source | Recommendation | Confidence |
|---|---|---|---|---|---|
| 1 | Path param `id` | param | audit | KEEP | high |
| 2 | `ratingAvg`, `reviewCount` | response field | audit finding 3 | VERIFY WITH OTHER CLIENT FIRST; do not remove | medium |
| 3 | `watchersCount` | response field | audit finding 4 | VERIFY WITH OTHER CLIENT FIRST | medium |
| 4 | `likeCount`, `commentCount` | response field | audit finding 5 (shared list DTO) | KEEP | medium |
| 5 | `negotiable`, `minOfferPercent`, `attributes[]`, `shippingTier`, `videoUrl`, `stock`, `subcategoryId`, `typeId` | response fields | audit "Looks unused but keep" | KEEP | high |
| 6 | 404 and 200 schema undocumented | spec | ST103; TC-038-034, 035, 003, 006, 010 | FIX SPEC | high |
| 7 | Optional auth not declared | spec | TC-038-067; audit finding 9 | FIX SPEC | high |
| 8 | TRACE / unsupported-method 405 | behaviour | ST204 | VERIFY intended behaviour first | low |
| 9 | `ResumeDraft.tsx` calls without a token | client | audit finding 6 | VERIFY WITH OTHER CLIENT FIRST | high |

No REMOVE recommendation is made.

## Defects (see bugs.md)
Only spec/documentation gaps are confirmed, plus potential-defect items. Draft, inactive and rejected listings are readable anonymously: conflicts with the sheet title, matches code and BRI-44.

## Unresolved expectations and conflicts
TC-038-013 (draft, Conflict), 016 (inactive, Unclear), 023 (rejected, Conflict), 025 (Unclear), 027 (soft-deleted 404 for everyone, Conflict), 047 (admin on soft-deleted, Conflict), 051 (expired token, Conflict), 063 (removed listing visible to owner, Conflict), 067 (spec declares no auth, Conflict). Sheet vs code: the code hides only `pending_approval` (`listings.service.ts:60,786`); no `removed` status exists (`schema.prisma:36-45`); soft-delete returns 404 for everyone (`listings.repository.ts:692-704`).

## Open High findings from the independent case review (testcases\reviews\EP-038-review.md) - verdict REWORK
1. TC-061/062 vs TC-027/047/063: same soft-deleted state judged Confirmed and Conflict; TC-047 matches [200], TC-062 matches [404].
2. TC-059/060/026 vs TC-013/016: draft/inactive/rejected for anon judged three ways.
3. Missing security case: shared `listing:<id>` cache (owner GET pending_approval, then guest GET, expect 200 then 404).
4. "Confirmed" claimed on code/existing-test backing only: TC-049, 053, 055, 056, 064, 065, 066, 068, 069.

Until fixed, verdicts on TC-013, 016, 023, 047, 059, 062 and others named above are not authoritative.

## Cases needing another execution method
TC-038-026 to 033, 041, 045, 049, 050, 051, 054, 058, 066, 067. Review also lists missing cases: cache cross-viewer leak, malformed JWT, private seller fields on the anon response, malformed ids, HEAD/OPTIONS.

## Could not verify
Response content of the 200 body (no schema); soft-deleted behaviour for owner/admin (no fixture); cache gate across roles and expired-token handling; the reason behind TC-038-008's FAIL (inferred). Code locations come from the audit and were not re-read by the triager.
