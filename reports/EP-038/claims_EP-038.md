# Claim verification - EP-038.md

116 citations: WARN_NOFILE 9, WARN_PARTIAL 3, WARN_DRIFT 2, WARN_ENCLOSING 1, OK_LOCATION_ONLY 72, OK 29

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 136 | `::234-238` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 186 | `::965-972` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 188 | `::956-959` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 189 | `::974-978` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 190 | `::980-984` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 194 | `::775` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 195 | `::986-993` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 196 | `::999-1007` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 197 | `::945-949` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 81 | `listing.constants.ts:60-68` | WARN_PARTIAL | found: NOT_DELETED; NOT at the cited lines: findFirst |
| 191 | `docs/domain.md:75` | WARN_PARTIAL | found: Listing; NOT at the cited lines: message, found (elsewhere in file: {'found': [298]}) |
| 192 | `docs/domain.md:75` | WARN_PARTIAL | found: Listing; NOT at the cited lines: message, found (elsewhere in file: {'found': [298]}) |
| 64 | `listings.service.ts:786-788` | WARN_DRIFT | symbol(s) ADMIN are within 15 lines of the cited range, not inside it (line numbers moved?) at {'ADMIN': [785]} |
| 91 | `ProductDetail.tsx:360` | WARN_DRIFT | symbol(s) listing, negotiable are within 15 lines of the cited range, not inside it (line numbers moved?) at {'listing': [35, 47, 67, 87, 96, 120], 'negotiable': [367]} |
| 83 | `listingsApi.ts:62` | WARN_ENCLOSING | cited lines are inside 'ListingDto' (declared at line 54), not on a line that names it |

(OK rows omitted from this table; full list in the JSON)
