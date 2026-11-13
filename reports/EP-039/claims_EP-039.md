# Claim verification - EP-039.md

38 citations: WARN_NOFILE 1, OK_LOCATION_ONLY 21, OK 16

FAIL = the claim is wrong or unverifiable (file/line/symbol does not match). WARN = probably right but check it. OK_LOCATION_ONLY = the file and lines exist but nothing was quoted to compare.

| Audit line | Citation | Status | Detail |
|---|---|---|---|
| 55 | `::2286-2296` | WARN_NOFILE | line-only citation (':N') with no file named on the same line - cannot be verified; name the file next to the number |
| 22 | `listings.service.spec.ts:2230-2386` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 23 | `docs\features\delist-relist-offer-cancellation.md:9` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 27 | `src\screens\profile\SellerListingDetail.tsx:348-357` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 31 | `src\lib\types.ts:38` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 31 | `src\app\admin\platform-settings\page.tsx:109` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 52 | `listings.controller.ts:97-98` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 53 | `listings.service.ts:1303-1319` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 54 | `listings.service.spec.ts:2241-2269` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 59 | `schema.prisma:38` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 71 | `listingsApi.ts:270-271` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 88 | `listings.service.ts:1320-1360` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 88 | `listings.service.spec.ts:2241-2269` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 89 | `listings.service.ts:1001` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 89 | `schema.prisma:36-45` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 90 | `listings.service.ts:1320-1360` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 90 | `listings.service.ts:1362-1379` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 91 | `SellerListingDetail.tsx:198-207` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 92 | `src\lib\types.ts:38` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 92 | `src\app\admin\platform-settings\page.tsx:109` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 108 | `listings.controller.ts:100` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 109 | `SellerListingDetail.tsx:198` | OK_LOCATION_ONLY | no symbol quoted next to the citation; file and line range verified |
| 15 | `apps\api\src\listings\listings.controller.ts:100-109` | OK | all quoted symbols found at the cited lines: relistListing |
| 16 | `apps\api\src\listings\listings.service.ts:1320-1360` | OK | all quoted symbols found at the cited lines: ListingsService.relistListing |
| 17 | `listings.service.ts:958-1117` | OK | all quoted symbols found at the cited lines: createListing |
| 18 | `listings.service.ts:240-306` | OK | all quoted symbols found at the cited lines: toListingDto |
| 18 | `listings.service.ts:234-238` | OK | all quoted symbols found at the cited lines: mapStatus |
| 19 | `listings.repository.ts:941-946` | OK | all quoted symbols found at the cited lines: findByIdForOwnerWithImages |
| 19 | `listings.repository.ts:831-910` | OK | all quoted symbols found at the cited lines: createListing |
| 20 | `apps\api\prisma\schema.prisma:36-45` | OK | all quoted symbols found at the cited lines: ListingStatus |
| 21 | `listings.service.ts:1362-1379` | OK | all quoted symbols found at the cited lines: updateListingStatus |
| 26 | `src\services\listingsApi.ts:240-251` | OK | all quoted symbols found at the cited lines: CreatedListingDto |
| 26 | `src\services\listingsApi.ts:267-271` | OK | all quoted symbols found at the cited lines: relistListing |
| 27 | `src\screens\profile\SellerListingDetail.tsx:190-231` | OK | all quoted symbols found at the cited lines: relist, confirmRelist |
| 59 | `listings.service.ts:1001` | OK | all quoted symbols found at the cited lines: pending_approval |
| 72 | `SellerListingDetail.tsx:194-218` | OK | all quoted symbols found at the cited lines: relist |
| 72 | `SellerListingDetail.tsx:220-231` | OK | all quoted symbols found at the cited lines: confirmRelist |
| 72 | `SellerListingDetail.tsx:350-357` | OK | all quoted symbols found at the cited lines: ManageRow |
