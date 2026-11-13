# Module: payment-methods

**Endpoints** (all under `@Controller('me/payment-methods')`, class-level `@UseGuards(JwtAuthGuard)` — `payment-methods.controller.ts:19-20`, so every route here requires a valid, live-loaded user; no public routes in this module):

- `GET /me/payment-methods` — `payment-methods.controller.ts:25-28`
- `POST /me/payment-methods` — `payment-methods.controller.ts:30-42`
- `DELETE /me/payment-methods/:id` — `payment-methods.controller.ts:44-52`

---

## Controller → Service → Repository trace

- **Controller**: thin — pulls `req.user.id` and delegates straight to `PaymentMethodsService`. `delete()` returns `@HttpCode(HttpStatus.NO_CONTENT)` (204) with no body.
- **Service**: `PaymentMethodsService` (`payment-methods.service.ts`) — holds all business logic (idempotency, brand validation, Stripe error translation, the BRI-816 offer-hold guard).
- **Repository**: `PaymentMethodsRepository` (`payment-methods.repository.ts`) — thin Prisma wrapper, no business logic.
- **Cross-module dependency**: `PaymentMethodsService` injects `OffersRepository` directly (not `OffersModule`/`OffersService`) — `payment-methods.module.ts:6-13`'s comment documents this as a **deliberate, explicit exception** to the "never reach into another module's repository directly" rule, mirroring the identical shape `offers.module.ts` already uses for `OrdersRepository`. Reason: `OffersModule` already `forwardRef`-imports this module (an offer requires a valid card on file), so importing `OffersModule` back here would stack a second cycle on top of the existing Offers↔Payments one; `OffersRepository` has no deeper dependency chain or business logic to bypass. **Not a gap** — it's a documented, reviewed boundary call, but worth knowing when tracing "does this module ever skip a layer."
- **DTO**: `AttachPaymentMethodDto` (`dto/attach-payment-method.dto.ts`) — one required string field, `stripePaymentMethodId`. `GET`/`DELETE` take no body (DELETE's `:id` is a plain `@Param`).

## `GET /me/payment-methods`

Returns all of the caller's saved `PaymentMethod` rows, ordered `isDefault desc, createdAt desc`. **`isDefault` is a schema/DTO field that no code path ever sets to `true`** — `create()` always inserts with the Prisma default (`false`), and there is no PATCH/set-default endpoint anywhere in this controller or any other module's grep hits. In practice this sort is always just "newest first." Flagged in gaps as dead functionality, not a bug per se (nothing is broken — the field simply does nothing).

## `POST /me/payment-methods` — `attach()` (`payment-methods.service.ts:74-171`)

Order of operations, each a real branch a test should cover:

1. **Exact-id idempotency** (BRI-434): if the caller's `stripePaymentMethodId` is already saved for this user, return that row immediately with `alreadySaved: true` — **no Stripe call at all**.
2. **Stripe customer resolution**: if the user has no `stripeCustomerId` yet, create one (`StripeService.createCustomer`) and persist it.
3. **Attach to Stripe**, with one layer of self-healing: a `resource_missing`/`param: customer` failure (stale/cross-environment customer id — "confirmed live on QA") triggers exactly one retry: recreate the customer, retry the attach once more. Any other Stripe error (or a second failure after the retry) is mapped by `toHttpError` — `StripeCardError`/`StripeInvalidRequestError` → 400 with Stripe's own message; anything else rethrows for a genuine 500.
4. **Id substitution**: the id Stripe actually attaches can differ from the one sent (a test alias like `pm_card_visa` is cloned to a fresh `pm_…` id every time — BRI-436). If the *attached* id already has a saved row (can happen after the substitution), that row is returned with `alreadySaved: true`.
5. **Brand allow-list** (BRI-238): only `visa`/`mastercard`/`amex`/`discover` (`common/constants/card-brands.constant.ts`) may be saved. A refused brand is retrieved from Stripe (so its brand is even known), then **detached again** so nothing refused lingers on the Stripe customer, then rejected with a fixed 400 message.
6. **Same-physical-card idempotency**: even with a new Stripe id, if a saved row already matches brand+last4+expMonth+expYear for this user, that row is returned (`alreadySaved: true`) and the just-attached clone is detached (best-effort; a detach failure here is only logged, not surfaced).
7. **Create**: only if none of the above matched — a genuinely new card.

**All of this idempotency is application-level `findFirst` logic, not a DB constraint** — see Gaps below (REDB1-39/BRI-434).

## `DELETE /me/payment-methods/:id` — `delete()` (`payment-methods.service.ts:173-207`)

1. `404` if the row doesn't exist.
2. `403 ForbiddenException` if `pm.userId !== callerId` (ownership check lives in the service, per `apps/api/CLAUDE.md`'s convention — not the guard).
3. **BRI-816 guard, checked before touching Stripe at all**: `409 ConflictException` if `OffersRepository.findOpenHoldingPaymentMethod(paymentMethodId)` finds an open (`pending`/`countered`, unexpired) offer whose manual-capture PaymentIntent hold is on this exact card. Prevents the historical bug where a buyer could remove a card that `acceptOffer` would still try to capture later. The DB read happens first precisely so a blocked delete never touches Stripe or the local row.
4. **Stripe detach**, tolerant of "already not attached to anyone" (`isAlreadyDetached` — covers both a clean `resource_missing` code and the no-code "not attached to a customer" message Stripe sends for a pre-BRI-436 test-alias row). Any *other* Stripe failure still maps through `toHttpError`.
5. **Hard delete** of the local row (`prisma.paymentMethod.delete`) — **no soft delete, no tombstone**.

### What happens to Orders/Offers that reference a deleted payment method
Neither `Order` nor `Offer` holds a live foreign key to `PaymentMethod` for its own history — both snapshot `cardBrand`/`cardLast4` (plain strings) at creation time (`Order.cardBrand`/`cardLast4`, confirmed in `schema.prisma`'s comment: "snapshotted... at order-creation time... the buyer may legitimately remove this card afterward... this is what order detail reads to show who was actually charged"). So deleting a `PaymentMethod` row **never corrupts past order/offer display** — it only affects (a) `GET /me/payment-methods`'s future listing and (b) any *future* attempt to charge that id, which is exactly what the BRI-816 guard above exists to prevent for the one case (an open offer hold) where a future charge is still pending.

## BRI-268 — server-side session/intent concept: none found

The task asked whether `payment-methods` has any server-side notion of "where this payment method was being added for" (Checkout vs. an offer gate), given that BRI-268's fix was mobile-only navigation (`nav.replace` to an explicit `OfferReturnTo` destination instead of a bare `goBack()`). Traced `PaymentMethod.tsx` (`apps/mobile/src/screens/checkout/PaymentMethod.tsx`): the `returnTo` destination lives **entirely in React Navigation route params** (`route.params?.returnTo`), threaded through from whichever screen pushed this one, and is consulted only by the client-side `finish()` function after a successful `attach()` call. The `POST /me/payment-methods` call itself (`checkoutApi.attachPaymentMethod`) sends only `{ stripePaymentMethodId }` — no flow/intent/context field exists in `AttachPaymentMethodDto`, and nothing server-side is aware an offer vs. a checkout initiated the add.

**This is confirmed to be a frontend-only state-management concern with no backend counterpart.** Worth recording explicitly (per the task's own framing) because it means: (a) no API test can exercise "was this card added for an offer" — that predicate doesn't exist server-side; (b) a regression of BRI-268 would be invisible to any payment-methods API test and can only be caught by a mobile navigation test (already covered: `apps/mobile/src/screens/offer/__tests__/OfferPaymentMethodSheet.test.tsx` and the `PaymentMethod.test.tsx` suite per `apps/mobile/CLAUDE.md`).

## Known gaps / Linear-sourced findings (see fragments/payments-shipping.gaps.md for full detail)

- **REDB1-39 / BRI-434** (status at analysis time: **Reopened**) — the idempotency logic above (steps 1/6 in `attach()`) is confirmed live and working per the dev's own comment ("Verified live on the dev API: `pm_card_visa` attached twice → one row"), but the ticket stays open because (a) there is **no DB-level unique constraint** backing it — a genuine race between two concurrent identical `POST` calls can still both pass the `findFirst` check and insert two rows — and (b) pre-existing duplicate rows already in the shared DB (documented example: user `cmu29mwkx006l3krupp0gctse`, three rows for the same `pm_card_visa`) were never cleaned up, explicitly pending sign-off since that's a data change on a shared, real database (this analysis does not touch it, per the hard database-safety rule).
- **REDB1-124 / BRI-823** (status: Todo) — a `PaymentMethod` row that becomes detached from Stripe out-of-band (Dashboard action, or Stripe-side expiry) is never revalidated by this module. `GET /me/payment-methods` keeps listing it; nothing here calls Stripe to confirm it's still attached. The failure only surfaces downstream, at checkout, where `orders.service.ts`'s Stripe-error mapping doesn't currently catch this specific error type and leaks Stripe's raw message to the buyer. **Module boundary**: the fix (friendly error message) belongs in `orders.service.ts`, not here — but the root condition (a stale local row with no re-validation) is this module's data model.

## Tests

`payment-methods.service.spec.ts` (~20KB) is the primary suite — covers idempotent attach (exact-id and same-card paths), brand rejection + detach-on-reject, stale-customer-id recovery, the BRI-816 open-offer-hold guard, and both `isAlreadyDetached` shapes on delete. Mocks `PaymentMethodsRepository`/`StripeService`/`OffersRepository`, not Prisma — per the layer-testing convention.
