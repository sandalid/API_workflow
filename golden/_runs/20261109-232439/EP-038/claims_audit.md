# Claim verification - audit.md

82 citations: WARN_DRIFT 1, OK_LOCATION_ONLY 26, OK 55

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 178 | `listings\listings.service.spec.ts:965` | WARN_DRIFT | symbol(s) still, returns, listing, buyer are within 15 lines of the cited range, not inside it (line numbers moved?) at {'still': [514, 557, 617, 839, 955, 966], 'returns': [59, 193, 287, 300, 308, 511], 'listing': [5, 1 |

(OK rows omitted from this table; full list in the JSON)
