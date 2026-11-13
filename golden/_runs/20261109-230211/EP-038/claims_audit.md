# Claim verification - audit.md

75 citations: WARN_DRIFT 3, WARN_ENCLOSING 1, OK_LOCATION_ONLY 24, OK 47

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 71 | `prisma\schema.prisma:36` | WARN_DRIFT | symbol(s) reserved are within 15 lines of the cited range, not inside it (line numbers moved?) at {'reserved': [44, 93, 764, 768, 770]} |
| 85 | `listings\listings.service.spec.ts:945` | WARN_DRIFT | symbol(s) offerCount are within 15 lines of the cited range, not inside it (line numbers moved?) at {'offerCount': [217, 948, 996]} |
| 113 | `listings\listings.service.ts:48` | WARN_DRIFT | symbol(s) draft are within 15 lines of the cited range, not inside it (line numbers moved?) at {'draft': [51, 62, 63, 74, 795, 991]} |
| 55 | `apps\mobile\src\services\listingsApi.ts:308` | WARN_ENCLOSING | cited lines are inside 'getListing' (declared at line 307), not on a line that names it |

(OK rows omitted from this table; full list in the JSON)
