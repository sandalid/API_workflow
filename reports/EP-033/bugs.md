# EP-033 - Bug report

### BUG-EP033-01 - TRACE on /categories returns 405 without the required `Allow` header
- Severity: low
- Type: App bug (framework/platform default behavior) — likely systemic across the whole API, not specific to this controller
- Endpoint / Env / Role: `GET /categories` (tested with `TRACE`) / `https://api-qa.redspur.com/api` / user
- Steps to reproduce:
  ```
  curl -X TRACE https://api-qa.redspur.com/api/categories
  st replay gJqkGW
  ```
- Expected: Per RFC 9110 §15.5.6, any 405 response must include an `Allow` header listing the methods that are actually supported on this route.
- Actual: HTTP 405 with no `Allow` header (results_detail.csv row 5: `case gJqkGW, TRACE, 405, check=unsupported_method, failure_code=ST204`).
- Check / code: `unsupported_method` (ST204); Occurrences: 1; Example case ID: `gJqkGW`.
- Suspected location: no global exception filter or middleware exists in `apps\api\src\main.ts` that sets an `Allow` header on method-not-allowed responses (grepped, no matches for TRACE/Allow/405). TRACE appears to be rejected by the underlying Node HTTP server/Nest platform layer before it reaches app routing, which is why no `Allow` header is attached. Suggested fix: add a small global filter/middleware that sets `Allow` on 4xx method-not-allowed responses, or confirm this is an accepted platform limitation and document it. Confidence low — this is inferred from the absence of app-level handling, not a specific line that causes it.
- Business impact: Minor HTTP-compliance gap; will recur on every endpoint in the API (not unique to EP-033) and will keep tripping strict API-conformance scanners.

### BUG-EP033-02 - QUERY on /categories returns 404 instead of 405
- Severity: low
- Type: App bug (framework/platform default behavior) — likely systemic across the whole API, not specific to this controller
- Endpoint / Env / Role: `GET /categories` (tested with `QUERY`) / `https://api-qa.redspur.com/api` / user
- Steps to reproduce:
  ```
  curl -X QUERY https://api-qa.redspur.com/api/categories
  st replay cbloDm
  ```
- Expected: an unmapped-but-reasonable HTTP method on a path that exists should return `405 Method Not Allowed`, not `404 Not Found` (Schemathesis's `unsupported_method` check expectation).
- Actual: HTTP 404 (results_detail.csv row 11: `case cbloDm, QUERY, 404, check=unsupported_method, failure_code=ST204, "Unsupported method QUERY returned 404, expected 405 Method Not Allowed"`).
- Check / code: `unsupported_method` (ST204); Occurrences: 1; Example case ID: `cbloDm`.
- Suspected location: no custom routing/404/405 handling found in `apps\api\src\main.ts`. `QUERY` is a newer/unregistered HTTP method in Express's default method table, so it falls through to Express/Nest's generic "no matching route" 404 handler rather than a method-not-allowed 405 — this is default framework behavior, not code specific to `CategoriesController`. Confidence low on exact fix location since no app-level code owns this behavior; fixing would require a global catch-all route/middleware that recognizes known paths and returns 405 for any method not in that path's allowed set.
- Business impact: Low; `QUERY` is not yet in common client use, but the 404-vs-405 mismatch is systemic to the whole API and will show up identically in every other endpoint's run, not just EP-033.
