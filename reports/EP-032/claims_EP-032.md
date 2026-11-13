# Claim verification - EP-032.md

68 citations: FAIL_LINE 1, FAIL_SYMBOL 1, WARN_PARTIAL 1, WARN_DRIFT 1, OK_LOCATION_ONLY 47, OK 17

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 80 | `brands.repository.spec.ts:1-27` | FAIL_LINE | cited 1-27 but the file has 26 lines |
| 29 | `listings\listings.service.ts:374` | FAIL_SYMBOL | quoted symbol(s) findById are not at the cited lines; found elsewhere in the file at lines {'findById': [171, 769, 774, 794, 821, 964]} |
| 26 | `prisma\schema.prisma:514-524` | WARN_PARTIAL | found: Brand, name, slug, logo, navigationTab, createdAt; NOT at the cited lines: Material (elsewhere in file: {'Material': [526, 532, 2228]}) |
| 29 | `saved-searches\saved-searches.service.ts:78` | WARN_DRIFT | symbol(s) findById are within 15 lines of the cited range, not inside it (line numbers moved?) at {'findById': [85, 89, 182]} |

(OK rows omitted from this table; full list in the JSON)
