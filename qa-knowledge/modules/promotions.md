# Module: Promotions

1 endpoint, `apps/api/src/promotions/` (`promotions.controller.ts`, `promotions.service.ts`, `promotions.repository.ts`, `dto/validate-promo.dto.ts`). Backed by the `Promotion` Prisma model (`code`, `discountPct`, `active`, `expiresAt`).

Analyzed against commit `91e0447b`. Note: `admin/promotions` (list/create/delete) lives in `admin.controller.ts` — a separate module/batch — this module owns only the public validate-a-code route.

## `POST /promotions/validate` (`promotions.controller.ts:14-18`)

- **Auth**: `@UseGuards(JwtAuthGuard)` applied **at class level** — every route on this controller (i.e. this one route) requires a valid bearer token. No role/ownership check beyond authentication — any signed-in user can validate any promo code; this is a read/validate-only operation with no side effect on the `Promotion` row itself (confirmed: `validate()` only `findByCode` + conditional throws, no write).
- **Body**: `ValidatePromoDto` — `code: string`, `@IsString() @IsNotEmpty()`. No `@MaxLength` constraint was found on this field (contrast with e.g. `SearchHelpArticlesDto`'s `@MaxLength(200)`) — an arbitrarily long string is accepted by the DTO layer; the only effective bound is whatever `.toUpperCase()` and the subsequent Prisma unique lookup tolerate. Worth a boundary test (very long string → expect a clean "not valid" 400 rather than an unhandled error, since no DB row will match it regardless of length).
- **Business logic** (`PromotionsService.validate`, read in full):
  1. Looks up by `code.toUpperCase()` — **case-insensitive from the caller's perspective, case-sensitive-uppercase in storage**: a code is matched only if the uppercased input exactly equals the stored `code` column. This means a promo code must be seeded/created in **already-uppercase form** (confirmed by `seed.service.ts`'s `seedPromotions()`, which creates `code: 'YEEHAW'` — already uppercase) for this matching to work; a lowercase-stored code would never match any input, since the input is always uppercased before lookup but the stored value isn't normalized on the other side. Not re-verified against `admin.controller.ts`'s `POST /admin/promotions` creation DTO for whether it enforces uppercase on write — flag for cross-check during the `admin` batch.
  2. **Not found OR `active === false`** → same `BadRequestException` message either way (`Promo code "${code}" is not valid`) — a caller cannot distinguish "this code never existed" from "this code exists but was deactivated by admin." Deliberately or not, this is a single error path for two different underlying states; worth a test asserting the message/status is identical for both, since a tester might otherwise expect a different response for a deactivated vs. a nonexistent code.
  3. **Expired** (`expiresAt` set and in the past) → a **separate**, distinct message (`Promo code "${code}" has expired`) — this is the one case that IS distinguishable from the generic "not valid" response. A promo with no `expiresAt` set (nullable field) never hits this branch regardless of age.
  4. Success → `{ code, discountPct, description }` where `description` is server-generated (`"${discountPct}% off your order"`) — not stored on the `Promotion` row itself (no `description` column referenced), so the human-readable text is derived fresh every validation call, not an admin-editable field (not independently re-verified against the `Promotion` Prisma model's full column list in this pass — the service only reads `code`/`discountPct`/`active`/`expiresAt`, which is what this finding is based on).
- **No reservation/consumption of the code happens here** — validating a code does not mark it used, does not decrement a usage counter (no usage-count column was referenced in the service), and does not create any row. This is a pure read + business-rule check; applying the discount at actual checkout (if that happens) is a separate concern this endpoint's own code does not perform — flag for cross-check against `orders`/`checkout` (already-analyzed module, `modules/orders.md`) to confirm whether/how a validated promo code is actually applied to an order total, since this endpoint alone does not do it.
- **No rate limiting specific to this endpoint was found** beyond the repo-wide global throttler (`apps/api/CLAUDE.md`: 100 req/min/IP) — a promo-code-guessing/enumeration concern given codes are short alphanumeric strings (`YEEHAW` is 6 characters) and the endpoint requires only authentication, not any rate-limit tier comparable to the auth endpoints' stricter 10/min throttle. Worth a dependency-map/gaps note: an authenticated user could brute-force-guess short promo codes at the global 100/min rate with no additional friction.

## Frontend usage

### Mobile

- `apps/mobile/src/services/checkoutApi.ts`'s `validatePromo(code, token)` — direct 1:1 wrapper, `POST /promotions/validate` with `{ code }` body and the bearer token. Called from the checkout flow (not independently traced to the exact screen file in this pass — `CheckoutSummary` test file references it, suggesting `CheckoutSummary`/`OrderReview`-adjacent screens are the consumer; confirm exact screen during consolidation if needed for a UI-level test scenario).

### Web

No reference found in `apps/web/src/lib` or `apps/web/src/app` to the public validate route — admin's own promo management (`admin/promotions` list/create/delete) is a separate, write-capable surface in a different module.

## Business-rule-relevant findings for consolidation

- **BR-PROMOTIONS-001**: validation requires authentication (any signed-in user), is read-only (no code consumption/usage tracking at this endpoint), and distinguishes only "expired" from "not valid for any other reason" (not-found and deactivated share one message/path).
- **BR-PROMOTIONS-002**: code matching is `input.toUpperCase() === stored_code` — a promo code must be stored in uppercase to ever match; confirm the admin-creation path enforces this during the `admin` batch's analysis, since nothing in this module itself normalizes a lowercase-created code.
- **Gap, not a rule**: no visible mechanism ties a successfully validated code to its actual application on an order total within this module's own code — that linkage, if it exists, lives in the orders/checkout path and should be confirmed there, not assumed here.
