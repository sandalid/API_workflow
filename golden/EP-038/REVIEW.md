# EP-038 - golden review sheet

A golden endpoint is only useful if its frozen outcomes are RIGHT. Read this, correct anything wrong in
facts.json / the frozen cases, then run: `python tools/golden.py approve EP-038 --by "<your name>"`.

Frozen from runs: user=RUN-20261109-195606-EP-038-user, admin=RUN-20261109-195944-EP-038-admin, anon=RUN-20261109-195807-EP-038-anon

## Frozen verdicts (what the matcher concludes from the frozen evidence)

| TC | Case | Role | Verdict |
|---|---|---|---|
| TC-038-001 | Unsupported method (TRACE) returns 405 with Allow header | user | FAIL |
| TC-038-002 | All other Schemathesis checks pass (11 checks / ~41 cases) | user | PASS |
| TC-038-003 | 200 body conforms to response schema | user | BLOCKED |
| TC-038-004 | Unsupported method (TRACE) returns 405 with Allow header | admin | FAIL |
| TC-038-005 | All other Schemathesis checks pass (11 checks / ~41 cases) | admin | PASS |
| TC-038-006 | 200 body conforms to response schema | admin | BLOCKED |
| TC-038-007 | Unsupported method (TRACE) returns 405 with Allow header | anon | FAIL |
| TC-038-008 | Response status code is documented in spec | anon | FAIL |
| TC-038-009 | All other Schemathesis checks pass (11 checks / ~41 cases) | anon | PASS |
| TC-038-010 | 200 body conforms to response schema | anon | BLOCKED |
| TC-038-011 | Draft listing visible to owner | user | PASS |
| TC-038-012 | Draft listing visible to Admin | admin | PASS |
| TC-038-013 | Draft listing NOT visible to anonymous | anon | FAIL |
| TC-038-014 | Inactive listing visible to owner | user | PASS |
| TC-038-015 | Inactive listing visible to Admin | admin | PASS |
| TC-038-016 | Inactive listing hidden from anonymous (per sheet intent) | anon | FAIL |
| TC-038-017 | Pending-approval listing visible to owner | user | PASS |
| TC-038-018 | Pending-approval listing visible to Admin | admin | PASS |
| TC-038-019 | Pending-approval listing hidden from anonymous | anon | PASS |
| TC-038-020 | Active, approved and sold listings visible | user | PASS |
| TC-038-021 | Active, approved and sold listings visible | admin | PASS |
| TC-038-022 | Active, approved and sold listings visible | anon | PASS |
| TC-038-023 | Rejected listing not visible to non-owner/non-admin | other | FAIL |
| TC-038-024 | Soft-deleted listing not visible to non-owner/non-admin | other | BLOCKED |
| TC-038-034 | 404 Listing not found is documented in spec | other | FAIL |
| TC-038-035 | 200 response has a body schema in spec | other | FAIL |
| TC-038-036 | 405 responses include Allow header | other | FAIL |
| TC-038-037 | Response status code is documented in spec | user | FAIL |
| TC-038-038 | Response status code is documented in spec | admin | FAIL |
| TC-038-039 | Guest opens a live listing on product detail (Flow 3) | anon | PASS |
| TC-038-040 | Logged-in user opens a live listing on product detail (Flow 3) | user | PASS |
| TC-038-042 | Seller opens own draft in listing management (Flow 18) | user | PASS |
| TC-038-043 | Seller opens own inactive and pending_approval listings (Flow 18) | user | PASS |
| TC-038-044 | Seller resumes draft; app sends NO token (Flow 18) | anon | PASS |
| TC-038-046 | Admin opens listing detail in every state incl. pending_approval and d | admin | PASS |
| TC-038-047 | Admin opens a soft-deleted listing (Flow 26) | admin | BLOCKED |
| TC-038-048 | Listing id that does not exist returns 404 | anon | PASS |
| TC-038-052 | Seller opens own rejected listing on status screen (Flow 18) | user | PASS |
| TC-038-055 | Reserved listing visible to any role (same bucket as sold/active/appro | anon | PASS |
| TC-038-056 | 200 response body never includes an offerCount key (BRI-54) | anon | PASS |
| TC-038-057 | id shaped like a different resource's id (e.g. an order id) still 404s | anon | no evidence |

## Cases with no machine-checkable match (not part of the verdict snapshot)
- TC-038-025 Draft/pending listing not visible to a second non-owner buyer
- TC-038-026 Visibility gate hides only pending_approval; draft, rejected and inactive are pu
- TC-038-027 Soft-deleted listing returns 404 for everyone including owner and Admin
- TC-038-028 ratingAvg and reviewCount still returned but unused by clients
- TC-038-029 watchersCount still returned but unused
- TC-038-030 likeCount and commentCount returned but unused (shared with list DTO)
- TC-038-031 ResumeDraft.tsx calls getListing without token; depends on draft being ungated
- TC-038-032 Offers-flow call sites (MakeOffer, OfferThread, SellerOfferDetail) not in Flow 3
- TC-038-033 Seller-web edit page call site not in sheet flows
- TC-038-041 Buyer/seller loads listing for an offer item card (MakeOffer, OfferThread, Selle
- TC-038-045 Seller web edit page loads own listing (Flow 18)
- TC-038-049 200 body carries the fields the apps read (negotiable, minOfferPercent, attribut
- TC-038-050 Tracked, not tested: items the app never uses
- TC-038-051 Seller screen calls with an expired/invalid Bearer token
- TC-038-053 Another seller (non-owner token) opens seller A pending_approval listing
- TC-038-054 After admin approves a pending listing, anonymous GET returns 200 (shared cache 
- TC-038-058 Unknown/extra query params (e.g. ?include=offers) are ignored; response unaffect

## Questions for the reviewer
1. Is every PASS/FAIL/BLOCKED above what you would conclude from the evidence?
2. Does facts.json list the findings a correct audit MUST contain, and the claims it must NOT make?
3. Are the required dimensions the scenarios a correct design must cover?
