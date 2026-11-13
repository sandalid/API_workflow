# EP-038 - independent case review (Phase B)

Reviewer: case-design-reviewer. Inputs: blind inventory (EP-038-blind.md) + EP-038-cases.json (69 cases).

**Verdict: REWORK - 4 High findings.** Same scenario judged both "Conflict" and "Confirmed" (sometimes with opposite expected statuses), "Confirmed" claimed on code/existing-test backing only, one security scenario missing.

| # | Sev | Type | Cases | Finding / suggested change |
|---|---|---|---|---|
| 1 | High | Wrong expectation / unsupported claim | TC-061, 062 vs TC-027, 047, 063 | Soft-deleted listing for owner/admin: 061/062 are Confirmed (404, Backend code) while 027/047/063 are Conflict/BLOCKED for the same state; 047 matches status [200], 062 matches [404]. Downgrade 061/062 to Assumed or BLOCKED; one expectation per scenario. |
| 2 | High | Wrong expectation / unsupported claim | TC-059, 060, 026, 013, 016 | Draft/inactive/rejected for anon judged three ways (059 PASS Confirmed; 026 FAIL with "matches audit"; 013/016 expect 404 BLOCKED). Make 059/060/026 Assumed (observed behaviour) and never FAIL, or tie them to BRI-44 / docs/domain.md:70. |
| 3 | High | Hole (security) | missing | Cache `listing:<id>` shared across viewers: no case for owner GET pending_approval then guest GET (expect 200 then 404). Needs ordered calls, not Schemathesis. |
| 4 | High | Unsupported claim | TC-049, 053, 055, 056, 064, 065, 066, 068, 069 | "Confirmed" with Backend code / Existing test / KB (code-derived) as source. Set to Assumed unless a ticket or fix-doc is cited. |
| 5 | Med | Wrong expectation | TC-068 | Owner-without-token 404 labelled Confirmed while its own business_outcome calls it a bug; duplicates TC-019. Cite BRI-781 or mark Assumed. |
| 6 | Med | Wrong expectation | TC-066 | BLOCKED reason wrong: PATCH /listings/:id (high-value threshold) and PATCH /listings/:id/status can move a live listing to pending_approval (KB BR-LISTINGS-006/008). |
| 7 | Med | Weak assertion | TC-059 | One verdict over three states with `in [draft, rejected, inactive]`; split per state, assert equals + seller block. |
| 8 | Med | Weak assertion | TC-011,012,014,015,017,018,042,043,044,046 | Status-only; 017/018 should assert listingStatus=pending_approval. |
| 9 | Med | Weak assertion / inconsistency | TC-041, 049 | Stated assertions not in the match; 049 BLOCKED yet "asserted in match"; 041 BLOCKED needlessly (live states do not depend on ownership). |
| 10 | Med | Weak assertion | TC-002, 005, 009 | Expected text claims more than the match checks. |
| 11 | Med | Hole | missing | Malformed Bearer token on approved (200) and pending_approval (404): executable without extra fixtures; only TC-051 (expired token, BLOCKED) exists. |
| 12 | Med | Hole | missing | No check that anonymous response omits private seller fields (email/phone). |
| 13 | Med | Inconsistency | TC-023..026, 028-032, 034-036, 050, 067 | Role column "other" vs match.role anon/user/any; scenario text mismatches. |
| 14 | Med | Inconsistency / executability | TC-011..022, 025, 043, 045 | Preconditions cite ids not in fixtures.json; notes say "no rejected/reserved fixture" while other cases use them. |
| 15 | Low | Duplicate | TC-001/004/007/036 etc. | Same TRACE-405 and undocumented-404 checks repeated across roles. |
| 16 | Low | Duplicate | TC-042/043/046, 031/044, 025/053, 028-030/050, 032/041, 033/045 | Same role/ownership/state/assertions; 025 Unclear vs 053 Confirmed. |
| 17 | Low | Unsupported claim | TC-008,034-038 | "Confirmed" with OpenAPI/RFC; spec gaps filed as bugs; TC-001/004/007 "likely noise" yet FAIL. |
| 18 | Low | Inconsistency | TC-031,035,045,052,067 | Field/status mismatches (Manual vs Schemathesis, PASS with null match, etc.). |
| 19 | Low | Weak assertion | TC-048, 057, 058 | Tighten. |
| 20 | Low | Hole | missing | No specific malformed-id cases (long, unicode, ../, whitespace) and no HEAD/OPTIONS. |

## Holes (blind inventory with no case)
#22 cache cross-viewer leak; #18/#19 malformed JWT; #25 private seller fields; #28 status mapping; #16 malformed ids; #26 HEAD/OPTIONS; admin take-down reflected immediately by anon GET (BRI-438).

## Could not judge
Fixture-id validity, harness op semantics (exists/absent/equals), whether a second buyer account exists, whether PASS/FAIL results are right (evidence not read).
