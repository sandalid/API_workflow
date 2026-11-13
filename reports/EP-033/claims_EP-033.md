# Claim verification - EP-033.md

107 citations: WARN_PARTIAL 1, WARN_DRIFT 1, OK_LOCATION_ONLY 79, OK 26

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 61 | `categories.repository.ts:17-19` | WARN_PARTIAL | found: name, sortOrder; NOT at the cited lines: slug, icon, image, createdAt, updatedAt (elsewhere in file: {'slug': [22, 31, 33, 55, 64, 81], 'icon': [56], 'image': [57, 65, 69, 70, 71, 77]}) |
| 51 | `docs\features\taxonomy-tree.md:60` | WARN_DRIFT | symbol(s) name are within 15 lines of the cited range, not inside it (line numbers moved?) at {'name': [8, 25, 26, 28, 66, 74]} |

(OK rows omitted from this table; full list in the JSON)
