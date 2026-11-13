# Claim verification - EP-109.md

124 citations: FAIL_SYMBOL 1, WARN_PARTIAL 7, WARN_ENCLOSING 5, OK_LOCATION_ONLY 87, OK 24

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 167 | `sellers.service.ts:1272-1273` | FAIL_SYMBOL | quoted symbol(s) getSellerByIdForAdmin are not at the cited lines; found elsewhere in the file at lines {'getSellerByIdForAdmin': [1294]} |
| 23 | `sellers\sellers.repository.ts:12-17` | WARN_PARTIAL | found: findUserWithProfile, prisma.user.findUnique, sellerProfile, sellerBankAccount; NOT at the cited lines: suspended (elsewhere in file: {'suspended': [381]}) |
| 29 | `admin\admin.repository.ts:366-368` | WARN_PARTIAL | found: updateUserSuspended, suspended; NOT at the cited lines: isSeller (elsewhere in file: {'isSeller': [280, 325]}) |
| 49 | `components\UnifiedLogin.tsx:74,145-146` | WARN_PARTIAL | found: err.message; NOT at the cited lines: Account, suspended |
| 80 | `sellers.repository.ts:12-17` | WARN_PARTIAL | found: User; NOT at the cited lines: suspended (elsewhere in file: {'suspended': [381]}) |
| 92 | `authApi.ts:236` | WARN_PARTIAL | found: wrong; NOT at the cited lines: OtpErrorKind (elsewhere in file: {'OtpErrorKind': [119, 135, 140]}) |
| 181 | `roles.guard.ts:55-61` | WARN_PARTIAL | found: Insufficient, permissions; NOT at the cited lines: message |
| 184 | `auth.service.ts:166-168` | WARN_PARTIAL | found: Account, suspended; NOT at the cited lines: message (elsewhere in file: {'message': [58, 197, 213, 294, 316, 328]}) |
| 37 | `services\sellersApi.ts:335` | WARN_ENCLOSING | cited lines are inside 'getProfile' (declared at line 334), not on a line that names it |
| 44 | `sellers.service.ts:500-523` | WARN_ENCLOSING | cited lines are inside 'getProfile' (declared at line 495), not on a line that names it |
| 47 | `lib\sellerApi.ts:355` | WARN_ENCLOSING | cited lines are inside 'getProfile' (declared at line 354), not on a line that names it |
| 81 | `sellers.service.ts:1311-1312` | WARN_ENCLOSING | cited lines are inside 'getSellerByIdForAdmin' (declared at line 1294), not on a line that names it |
| 107 | `jwt.strategy.ts:42` | WARN_ENCLOSING | cited lines are inside 'JwtStrategy.validate' (declared at line 34), not on a line that names it |

(OK rows omitted from this table; full list in the JSON)
