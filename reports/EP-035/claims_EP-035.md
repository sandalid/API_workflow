# Claim verification - EP-035.md

61 citations: WARN_PARTIAL 2, WARN_DRIFT 1, WARN_ENCLOSING 3, OK_LOCATION_ONLY 35, OK 20

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 10 | `droplight\apps\api\src\listings\listings.repository.ts:343-409` | WARN_PARTIAL | found: findTrending, sort; NOT at the cited lines: trending (elsewhere in file: {'trending': [60, 413]}) |
| 43 | `ShopProfile.tsx:203,222` | WARN_PARTIAL | found: getListingsBySeller, userId, sold; NOT at the cited lines: page, limit (elsewhere in file: {'page': [59, 63, 78, 94, 98, 108]}) |
| 62 | `listings.controller.ts:43,186-187` | WARN_DRIFT | symbol(s) findMany are within 15 lines of the cited range, not inside it (line numbers moved?) at {'findMany': [188, 189]} |
| 17 | `droplight\apps\mobile\src\store\productsStore.ts:188-191` | WARN_ENCLOSING | cited lines are inside 'fetchFeed' (declared at line 167), not on a line that names it |
| 44 | `listings.repository.ts:250-256` | WARN_ENCLOSING | cited lines are inside 'buildFilterWhere' (declared at line 186), not on a line that names it |
| 45 | `listings.repository.ts:236-240` | WARN_ENCLOSING | cited lines are inside 'buildFilterWhere' (declared at line 186), not on a line that names it |

(OK rows omitted from this table; full list in the JSON)
