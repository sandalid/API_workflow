# Module: Uploads

13 endpoints, `apps/api/src/uploads/` (`uploads.controller.ts`, `uploads.service.ts`, `file-count-limit.interceptor.ts`). **Correction to this knowledge base's own earlier architecture note**: `overview.md`'s original draft speculated upload storage might be "local-disk-only" based on `main.ts`'s `useStaticAssets(join(process.cwd(), 'uploads'), { prefix: '/uploads' })` line — reading `uploads.service.ts` directly shows this is **wrong**; storage is **real AWS S3** (`@aws-sdk/client-s3`, `PutObjectCommand`/`GetObjectCommand`, `@aws-sdk/s3-request-presigner`), not local disk. The `useStaticAssets` line in `main.ts` serves some other purpose (not independently identified in this pass) and is not where uploaded files actually live.

Analyzed against commit `91e0447b`. Evidence: in-code BRI citations (`BRI-489` file-count-limit message, `BRI-491`/`BRI-488` magic-byte content sniffing, `BRI-369` client-side video duration enforcement).

## Universal patterns across all 13 routes

- **Every upload is stored under a cryptographically random 96-bit filename**: `randomBytes(12).toString('hex')` + the real detected extension — confirmed identically in `uploadListingImages`, `uploadListingVideo`, `uploadProfileBuffer`, `uploadTaxonomyImage`, `uploadReviewImages`, `uploadEvidenceBuffer`. This is the load-bearing fact behind every unguarded `GET .../:filename` read route below: the filename is not guessable, so "no auth guard on the read route" does not mean "trivially enumerable."
- **Every read route redirects to a real S3 presigned URL** (`getPresignedUrl`, 1-hour expiry, `GetObjectCommand` via `@aws-sdk/s3-request-presigner`) — not a direct proxy of file bytes. A 404 on a bad/missing key is caught and logged at `warn`, then answered as a plain `404` with no body (not re-thrown as a NestJS exception) — confirmed identical across all six `get*` handlers.
- **Content-type is verified by magic bytes, not trusted from the client's extension/mimetype** for the image-upload paths — a `BRI-491`/`BRI-488` fix, cited directly in `uploadListingImages`'s own comment: "an `.exe` or `.txt` renamed to `photo.jpg` passed the [extension] check... and was written to S3 with a 200 [before this fix]." Confirmed this applies to the listings-photo path (`detectListingPhotoFormat`); not independently re-verified whether every other upload method (avatar/cover/taxonomy/review/evidence) applies the identical sniffing, versus only extension-checking — worth a direct per-method comparison during a future deeper pass, flagged here rather than asserted either way.

## 1. `POST /uploads/listings` (`:48-68`)

- **Guard**: `JwtAuthGuard` + `RolesGuard` + `@Roles('SELLER')`.
- **Interceptors, in a specific documented order**: `FileCountLimitInterceptor(MAX_LISTING_PHOTOS)` then `FilesInterceptor('files', undefined, { limits: { files: MAX_LISTING_PHOTOS } })`. The controller's own comment explains the non-obvious reason for using `limits.files` rather than `FilesInterceptor`'s own `maxCount` parameter: `maxCount` reports an over-limit submission as a generic Multer "Unexpected field" error, which `BRI-489` found unhelpful — the custom interceptor instead produces a message that **names the actual limit**.
- Accepts JPG/JPEG/PNG/WEBP/HEIC, ≤10MB/file (per the `@ApiOperation` description — exact byte-limit enforcement mechanism not independently re-verified at the Multer-config level for this specific route beyond the file-count limit already confirmed). A file with an unsupported extension is **skipped, not fatal to the whole batch** — `uploadListingImages`'s own comment states the per-file-reject reasoning (`fileFilter` can't selectively skip), and the response still returns `urls` for whatever *did* upload, plus the rejected filenames surfaced in a `BadRequestException` detail — meaning a batch with some rejects may still partially succeed before the exception is thrown; the precise contract (does a reject abort the whole request or return partial success?) reads as "reject blocks the request with a 400 naming the rejected files" from the service code — not independently confirmed whether already-uploaded-to-S3 files from the same batch are cleaned up on that rejection path (a potential orphan-object question, flag for `gaps-and-conflicts.md`).
- Zero files in the request → `BadRequestException('No files provided')`.

## 2. `POST /uploads/listing-video` (`:72-96`)

- Same guard. Single file, MP4/MOV/M4V, 50MB cap (`MAX_LISTING_VIDEO_BYTES`, its own separate limit from the 10MB photo cap). `limits.fileSize` on the Multer interceptor means an oversized upload is aborted **mid-stream** (producing a 413) rather than buffered fully into memory first — a deliberate resource-exhaustion defense, confirmed by the controller's own comment contrasting this with "the service's own size check only ever sees a file that already fit."
- **Duration (15s cap) is enforced client-side only** (`BRI-369`) — confirmed explicitly in the `@ApiOperation` description. No server-side video-duration check exists (the comment on a related internal method notes "the API has no ffprobe"). A test uploading a video over 15s via a non-UI path (direct API call) would succeed server-side — this is a real, acknowledged gap, not a defect to "fix" without a product decision, since adding ffprobe is nontrivial infra.

## 3. `GET /uploads/listing-videos/:filename` — public redirect, no guard (see universal pattern above).

## 4. `POST /uploads/taxonomy` (`:124-141`)

- **Guard**: `JwtAuthGuard` + `RolesGuard` + `@Roles(Role.ADMIN)` — the only upload route gated to the actual `Role` enum rather than the `'SELLER'` pseudo-role. Single file, no extension/size allowlist visible at the controller/interceptor level in this pass (plain `FileInterceptor('file', { storage: memoryStorage() })`, no `limits` object) — worth a direct test of an oversized/wrong-type taxonomy image to see what (if anything) rejects it, since the pattern established elsewhere (explicit allowlist + size cap) is not visibly present here.

## 5. `POST /uploads/avatar` (`:145-162`) / 6. `POST /uploads/cover` (`:166-183`)

- **Guard**: `JwtAuthGuard` only (any authenticated user, not seller-gated — makes sense, every account can have an avatar/cover regardless of seller status).
- Both **write directly into the caller's own user row** as a side effect (`users.updateAvatarUrl`/`updateCoverUrl`) — not a pure upload-and-return-url operation like the other routes; a test must account for this state mutation beyond just the response URL.
- Single file each, into `profiles/avatars/` or `profiles/covers/` respectively. No explicit allowlist/size cap visible in the controller for either (same gap noted for taxonomy above).

## 7. `GET /uploads/listings/:filename`, 8. `GET /uploads/taxonomy/:filename`, 9. `GET /uploads/profiles/:folder/:filename` — all public redirects, no guard, same pattern as #3.

- `profiles/:folder/:filename` accepts an arbitrary `folder` path segment — not independently verified whether this is validated against an allowlist (e.g. only `avatars`/`covers`) or passed straight into the S3 key unchecked; worth a direct test (`GET /uploads/profiles/../../etc/filename` or similar) to confirm the presigned-URL construction can't be coerced outside the intended prefix — flagged as an unresolved question, not asserted as a vulnerability, since S3 key construction via string template (`profiles/${folder}/${filename}`) combined with AWS's own key-namespacing may or may not be exploitable depending on bucket configuration not visible from this code alone.

## 10. `POST /uploads/reviews` (`:229-243`)

- **Guard**: `JwtAuthGuard` only. Up to **6** files (`FilesInterceptor('files', 6, ...)` — this one DOES use `maxCount` rather than the custom interceptor, an inconsistency with the listings-photo route's own documented reasoning for avoiding `maxCount`; not flagged as broken, since review photos may not need the same friendly-error treatment, but worth noting the two multi-file routes in this module use two different over-limit-handling strategies). JPG/JPEG/PNG/WEBP/HEIC, ≤5MB/file (smaller cap than the 10MB listing-photo limit). **Zero files is not an error here** — returns `{ urls: [] }` rather than throwing, the opposite behavior from `uploadListingImages`'s "No files provided" 400. A real, source-confirmed asymmetry between two superficially similar multi-file-upload endpoints in the same controller.

## 11. `GET /uploads/reviews/:filename` — public redirect, no guard.

## 12. `POST /uploads/refund-evidence` (`:260-277`)

- **Guard**: `JwtAuthGuard` only — **no ownership check at the upload step** (any authenticated user can call this and get back a URL; the actual linkage to a specific dispute/order presumably happens wherever this URL is later submitted, e.g. `PATCH /orders/:id/dispute/evidence` in the `disputes` module, already analyzed — cross-reference to confirm that endpoint, not this one, is where ownership is actually enforced). Single file, ≤5MB, same image-type allowlist.

## 13. `GET /uploads/evidence/:filename` — public redirect, **no guard**, same unguessable-filename mitigation as every other read route. This directly resolves the lead this knowledge base's own earlier planning notes flagged as a priority question ("is evidence/dispute photo access-controlled?") — the answer, source-confirmed: **no explicit authorization check on the read route itself**, mitigated entirely by filename unguessability (96-bit random token) and the 1-hour presigned-URL expiry on each individual redirect. This is architecturally identical to every other "public" upload read route in this module (listings/taxonomy/profiles/reviews) — evidence photos are not treated any more strictly than ordinary listing photos despite plausibly being more sensitive (a return/damage claim photo could show a buyer's home, a shipping label with an address, etc.). Worth flagging in `gaps-and-conflicts.md` as a genuine product/security question (should evidence photo access require proof of being a party to the specific dispute?) rather than asserting it's broken — the mitigations are real, just not identity-based.

## Frontend usage

### Mobile

- `apps/mobile/src/services/uploadsApi.ts` — generic `uploadImages(endpoint, uris, token)` helper reused across multiple upload types, client-side image compression (`compressManyForUpload`) before every upload, separate timeout budgets for image batches (60s) vs. video (180s).

### Web

- `apps/web/src/lib/api.ts` (`:292`) calls `POST /uploads/taxonomy` only — confirmed by direct grep, the admin taxonomy editor (`apps/web/src/app/admin/taxonomy/CategoryTree.tsx`) is this route's sole consumer. No other upload route has any web reference.

## Business-rule-relevant findings for consolidation

- **BR-UPLOADS-001 (correction)**: storage is real S3, not local disk — supersedes this knowledge base's own earlier speculative note in `overview.md`.
- **BR-UPLOADS-002**: every read route is unauthenticated by design, mitigated by 96-bit random filenames and 1-hour presigned-URL expiry on each redirect — uniform across listings/taxonomy/profiles/reviews/evidence, including dispute evidence photos, which are not treated more strictly despite plausibly higher sensitivity.
- **BR-UPLOADS-003**: `uploadListingImages` and `uploadReviewImages` handle the "zero files" and "over the count limit" cases differently from each other (400-vs-empty-array, and custom-interceptor-vs-`maxCount` respectively) — both are intentional-reading from the code, not obviously bugs, but worth explicit, separate test coverage rather than assuming parity.
- **BR-UPLOADS-004**: video duration (15s) is enforced client-side only — no server-side check exists; a direct-API test can upload a longer video successfully.
- **Unresolved, flagged honestly**: whether `profiles/:folder/:filename`'s `folder` param is allowlist-validated before use in the S3 key, and whether `uploads/taxonomy`/`avatar`/`cover` enforce any file-type/size limit at all given no `limits` object was visible on their interceptors — both need direct confirmation (a live or more deeply-read test) before writing a test scenario asserting either a pass or a fail.
