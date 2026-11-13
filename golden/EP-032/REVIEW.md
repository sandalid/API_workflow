# EP-032 - golden review sheet

A golden endpoint is only useful if its frozen outcomes are RIGHT. Read this, correct anything wrong in
facts.json / the frozen cases, then run: `python tools/golden.py approve EP-032 --by "<your name>"`.

Frozen from runs: user=RUN-20261109-184340-EP-032-user, admin=RUN-20261109-184418-EP-032-admin, anon=RUN-20261109-184435-EP-032-anon

## Frozen verdicts (what the matcher concludes from the frozen evidence)

| TC | Case | Role | Verdict |
|---|---|---|---|
| TC-032-001 | Anonymous GET /brands (no Authorization header) returns 200 with an ar | anon | PASS |
| TC-032-002 | Logged-in buyer token gets 200 with the full brand catalog, same shape | user | NOT RUN (partial) |
| TC-032-003 | Logged-in seller token gets 200 with the full brand catalog, same shap | other | no evidence |
| TC-032-004 | Logged-in admin token gets 200 with the full brand catalog, same shape | admin | NOT RUN (partial) |
| TC-032-010 | Raw HTTP response includes all 7 Brand fields (id, name, slug, logo, n | anon | NOT RUN (partial) |
| TC-032-011 | 200 body conforms to a documented response schema | anon | BLOCKED |
| TC-032-015 | Malformed/garbage Authorization header does not cause a 401/500 - no g | anon | PASS |
| TC-032-016 | Unsupported method (TRACE) returns 405 with an Allow header | anon | FAIL |
| TC-032-017 | All other Schemathesis checks pass (no 5xx, timing, auth or negative-d | anon | PASS |
| TC-032-018 | Schemathesis check 'unsupported_method' (ST204) - user | user | FAIL |
| TC-032-019 | Schemathesis check 'unsupported_method' (ST204) - admin | admin | FAIL |

## Cases with no machine-checkable match (not part of the verdict snapshot)
- TC-032-005 itemCount on a brand equals only its approved/active, non-deleted, non-mid-delet
- TC-032-006 A brand with zero live listings still appears in the list with itemCount: 0 (not
- TC-032-007 Response ordering: does GET /brands return the admin-curated/insertion order the
- TC-032-008 Guest Explore 'Shop by brand' taster rail (first 6 brands, TAXONOMY_RAIL_LIMIT) 
- TC-032-009 GET /brands/{anyId} does not exist as a route (mobile client's getBrandById is a
- TC-032-012 Exceeding 100 req/min from one IP returns 429 (global ThrottlerGuard)
- TC-032-013 Unexpected query params (?foo=bar, ?navigationTab=true) on a zero-param endpoint
- TC-032-014 Malformed/injection-style junk on an endpoint with no query params does not erro

## Questions for the reviewer
1. Is every PASS/FAIL/BLOCKED above what you would conclude from the evidence?
2. Does facts.json list the findings a correct audit MUST contain, and the claims it must NOT make?
3. Are the required dimensions the scenarios a correct design must cover?
