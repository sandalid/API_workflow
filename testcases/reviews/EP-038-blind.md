# EP-038 Phase A: blind inventory, GET /listings/:id

Saved from the case-design-reviewer's Phase A report (inputs: audit, OpenAPI spec, fixtures.json, qa-knowledge listings entries).

## Spec facts
- `ListingsController_findById`: one path param `id` (string); only response `200`, empty description.
- No response schema, no 404, no security, no format/pattern on `id` -> Schemathesis contract checks are vacuous. Only status-class, "no 5xx" and "unsupported method" checks are meaningful.

## Requirement status
- Sheet title: draft and removed listings hidden from everyone except owner and Admin.
- Code, unit tests and domain doc (BRI-44, BRI-366, BRI-636) contradict this; KB `modules/listings.md:125` agrees with the code (only `pending_approval` gated).
- No ticket/fix-doc backs the title; every code-derived expectation is "Assumed".

## Inventory (30 scenarios)
| # | Scenario | Role | State / input | Expected | Req. status | Schemathesis? |
|---|---|---|---|---|---|---|
| 1 | Approved listing | Guest | approved | 200, full DTO | Assumed | Yes (content = custom check) |
| 2 | Active listing | Guest | active | 200, listingStatus=active | Assumed | Yes |
| 3 | Sold / reserved, each role | all | sold, reserved | 200, status mapped | Assumed | Guest only |
| 4 | pending_approval, no token | Guest | pending_approval | 404 "Listing not found" | Assumed | Yes |
| 5 | pending_approval, buyer token | Buyer | pending_approval | 404 | Assumed | No (needs 2nd account) |
| 6 | pending_approval, owner token | Seller owner | pending_approval | 200 | Assumed | No (owner token) |
| 7 | pending_approval, admin token | Admin | pending_approval | 200 | Assumed | No (admin token) |
| 8 | Draft, guest/buyer | Guest, buyer | draft | code 200 / sheet 404 | Conflict -> BLOCKED | Guest only |
| 9 | Draft, owner/admin | Owner, admin | draft | 200 | Assumed | No (tokens) |
| 10 | Rejected / inactive, non-owner | Guest, buyer | rejected, inactive | code 200 / sheet silent | Conflict/Unclear -> BLOCKED | Guest only |
| 11 | "Removed" is not an enum status | any | n/a | n/a | Conflict -> BLOCKED | No |
| 12 | Soft-deleted, owner | Seller | deletedAt set | code 404 / sheet 200 | Conflict -> BLOCKED | No (no fixture) |
| 13 | Soft-deleted, admin | Admin | deletedAt set | code 404 / sheet 200 | Conflict -> BLOCKED | No |
| 14 | Soft-deleted, guest/buyer | non-owner | deletedAt set | 404 | Assumed; BLOCKED on fixture | No |
| 15 | Nonexistent valid-format id | Guest | unknown id | 404; spec gap (undocumented 404) | Assumed | Yes |
| 16 | Malformed ids (long, unicode, SQL/path traversal, %2e%2e) | Guest | odd id | 404, never 5xx | Assumed | Yes |
| 17 | Foreign-type id (order/user id) | Guest | foreign id | 404 | Assumed | Yes |
| 18 | Invalid/malformed/expired JWT on approved | any | approved | 200 as guest, no 401 | Assumed | Malformed yes; expired needs fixture |
| 19 | Invalid token on pending_approval | any | pending_approval | 404 | Assumed | Yes |
| 20 | Owner without token on own pending_approval | Owner | pending_approval, no auth | 404 | Assumed | Yes |
| 21 | Cache re-gate after status change | non-owner | status change between calls | 404 | Assumed | No (multi-step) |
| 22 | Cache cross-viewer leak | owner then guest | pending_approval | owner 200, guest 404 | Assumed | No |
| 23 | Unknown query params ignored | Guest | approved + ?include=offers | 200 same body | Assumed | Yes |
| 24 | Response omits offerCount / viewsCount | any | live | keys absent | Assumed | Custom check |
| 25 | No private seller fields | Guest | approved | seller block limited | Assumed | Custom check |
| 26 | Wrong methods HEAD/OPTIONS/PUT | Guest | any | 404/405, never 5xx (DELETE/PATCH exist: no destructive runs) | Assumed | Yes (unsupported_method) |
| 27 | Cross-user pending deep link | Buyer | pending_approval | 404 | Assumed | as #5 |
| 28 | Field types / status->listingStatus mapping | any | each live state | status in available/sold/reserved | Assumed | Custom |
| 29 | Dead fields (info only) | any | any | not a pass/fail | Assumed | Not a test |
| 30 | Comments allowed on pending listing GET hides | Buyer | pending_approval | other endpoint | Gap | No |

## Conflict rows (need BLOCKED cases)
1. Draft hidden from non-owners: sheet says hidden, code returns 200.
2. "Removed" is not a status; soft-delete 404s for everyone.
3. Soft-delete visibility for owner/admin: sheet implies visible, code 404s.
4. Rejected/inactive: sheet silent.

## Fixtures and accounts needed
- Listing ids per status in fixtures.json (draft, pending_approval, approved, active, rejected, inactive, sold, reserved), all owned by ST_USER. `_readme` says no rejected/soft-deleted exists on QA although a rejected id is listed: verify. `_owners_readme` says six listings, there are eight.
- Missing: soft-deleted listing; owner token not in fixtures; non-owner buyer token; admin token; expired and malformed JWT; a write route + restore for cache tests.

## What Schemathesis can verify
- `not_a_server_error`, status-code conformance, unsupported-method. Conformance fails on every 404 (only 200 documented): spec gap, not an API defect.
- Content-type, response-schema and response-headers conformance pass vacuously: Contract cases relying on them must be BLOCKED or reassigned.
- No multi-step flows, role switching, token expiry or cache manipulation. Rows 5-7, 9, 12-13, 21-22 need another method.

PHASE A complete.
