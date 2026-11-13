# EP-109 - golden review sheet

A golden endpoint is only useful if its frozen outcomes are RIGHT. Read this, correct anything wrong in
facts.json / the frozen cases, then run: `python tools/golden.py approve EP-109 --by "<your name>"`.

Frozen from runs: user=RUN-20261109-202832-EP-109-user, admin=RUN-20261109-202850-EP-109-admin, anon=RUN-20261109-202907-EP-109-anon

## Frozen verdicts (what the matcher concludes from the frozen evidence)

| TC | Case | Role | Verdict |
|---|---|---|---|
| TC-109-001 | Fetch own profile as an active, fully-onboarded seller returns 200 wit | user | PASS |
| TC-109-002 | Admin account (Role.ADMIN, not a seller) calling GET /sellers/me gets  | admin | PASS |
| TC-109-004 | Fetch with no Authorization header returns 401 | anon | PASS |
| TC-109-008 | Unknown/extra query params (e.g. ?foo=bar) sent to GET /sellers/me are | user | PASS |
| TC-109-012 | 200 response never includes an id key, despite mobile SellerProfile.id | user | PASS |
| TC-109-013 | 200 body conforms to a documented response schema | user | BLOCKED |
| TC-109-014 | Unsupported method (TRACE) on /sellers/me returns 405 with an Allow he | anon | FAIL |
| TC-109-015 | All other Schemathesis checks pass (no 5xx, timing, auth or negative-d | anon | PASS |
| TC-109-016 | Schemathesis check 'unsupported_method' (ST204) - user | user | FAIL |
| TC-109-017 | Schemathesis check 'unsupported_method' (ST204) - admin | admin | FAIL |
| TC-109-018 | Schemathesis check 'unsupported_method' (ST204) - anon | anon | FAIL |

## Cases with no machine-checkable match (not part of the verdict snapshot)
- TC-109-003 Logged-in non-seller USER (buyer, isSeller:false) calling GET /sellers/me gets 4
- TC-109-005 Pre-existing valid JWT; account suspended mid-session via admin action; replayin
- TC-109-006 Sheet-title-literal scenario: 'a suspended seller's own profile view clearly ref
- TC-109-007 No cross-account access vector exists on this route - there is no :id path param
- TC-109-009 Malformed/expired/tampered JWT on GET /sellers/me returns 401, no 500/leak
- TC-109-010 Session revoked via 'sid' check (e.g. sign out all devices) then retry GET /sell
- TC-109-011 Seller mid-onboarding (isSeller:true, sellerProfile:null, suspended:false) gets 

## Questions for the reviewer
1. Is every PASS/FAIL/BLOCKED above what you would conclude from the evidence?
2. Does facts.json list the findings a correct audit MUST contain, and the claims it must NOT make?
3. Are the required dimensions the scenarios a correct design must cover?
