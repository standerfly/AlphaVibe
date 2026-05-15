# Scope Decision: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Current Scope Status:** In Review; blocking clarification decisions CL-001, CL-003, and CL-005 are answered by SRC-005. Final product-spec acceptance is still pending.

## MVP In Scope

- AutoCharge shall use 203 Checkout as the FreeCharge order-level decision point for positive-amount CPO orders. [SRC-001]
- AutoCharge shall call Retail's FreeCharge eligibility API before finalizing a positive-amount eligible checkout as `Unpaid` and before payment starts. [SRC-001]
- AutoCharge shall resolve `vehicle_id` as a vehicle UUID and shall not send VIN, `car_no`, or `carId` as the Retail `vehicle_id` query parameter. [SRC-001]
- AutoCharge shall use the successful 202 ValidateCar request log `requestTime` as the Retail `charging_time` source; 203 `startTime` remains the order charging start time and duplicate-check input. [SRC-004]
- AutoCharge shall send Retail `charging_time` as RFC3339 UTC derived from the successful 202 ValidateCar request log `requestTime`; existing CPO/LXM timestamp fields remain epoch-millisecond strings. [SRC-005]
- AutoCharge shall create eligible Retail responses as `NoChargePromotion` for FreeCharge and skip payment and invoice issuance. [SRC-001, SRC-002, SRC-003]
- AutoCharge shall continue existing checkout status logic for non-eligible Retail responses, with payment allowed only for final status `Unpaid`. [SRC-001]
- AutoCharge shall create orders with a new `EligibilityPending` status for Retail query failures, Retail invalid-vehicle 4xx, or unusable eligibility inputs; it shall block payment and invoice and retry pending orders later. [SRC-001, SRC-002, SRC-003, SRC-005]
- AutoCharge shall create `EligibilityPending` when successful 202 eligibility inputs cannot be used for the Retail eligibility decision. [SRC-004]
- AutoCharge shall preserve existing 202 ValidateCar behavior and existing 203 validation, duplicate detection, order creation, fallback enrichment behavior, and HTTP contracts except where FreeCharge logic is explicitly inserted without contract changes. [SRC-001, SRC-005]
- AutoCharge shall preserve existing 202 ValidateCar blocker rules. A prior `EligibilityPending` FreeCharge order must not block future 202 ValidateCar requests and must not be treated as unpaid debt, failed payment, or outstanding payment. [SRC-006]
- AutoCharge shall preserve the existing 203 Checkout success response contract for FreeCharge and `EligibilityPending`: HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`. [SRC-005]
- AutoCharge shall preserve duplicate checkout `EC215` behavior and shall not call Retail for duplicate requests. [SRC-002, SRC-005]
- AutoCharge shall preserve existing `NoCharge` behavior for `amount == 0`; negative amount remains invalid input. [SRC-001, SRC-002]
- AutoCharge shall enforce payment and invoice guards so only `Unpaid` can enter payment, and `NoChargePromotion` or `EligibilityPending` orders cannot issue invoices. Guards must cover 203 Checkout, redo flows, payment helper functions, invoice helper functions, and scheduled jobs. [SRC-001, SRC-002, SRC-003]
- AutoCharge shall include reconciliation or alerting behavior for payment leakage, invoice leakage, and stuck pending orders, extending existing reports where needed. [SRC-001, SRC-002]

## Out Of Scope

- Retail eligibility creation and ownership. [SRC-001]
- Retail `has_promotions` creation or updates. [SRC-001]
- Retail Remote Control activation event handling. [SRC-001]
- Retail DMS `/getSaleOrder` query and DMS f16 sales category judgment. [SRC-001]
- Offline eligibility manual import owned by Retail or Business Unit. [SRC-001]
- APP promotion status display owned by Retail or APP. [SRC-001]
- AutoCharge determination of eligibility from order type, vehicle model, amount, DMS f16, card status, owner type, 202 result, VIN, or `car_no`. [SRC-001]
- Any change to existing CPO/LXM 202 ValidateCar or 203 Checkout HTTP request or response contract. [SRC-005]
- Any change to existing non-FreeCharge 202/203 behavior. [SRC-005]
- Any rule that blocks future 202 ValidateCar solely because a prior FreeCharge order is still `EligibilityPending`. [SRC-006]
- Retroactive FreeCharge grant for eligibility that becomes active after the successful 202 ValidateCar `requestTime`. [SRC-007]
- Eligibility evaluation based on charging-interval overlap, mid-session activation, 203 Checkout time, retry time, or post-202 campaign qualification changes. [SRC-007]

## Deferred Or Later

- FreeCharge trace table. [SRC-001]
- Campaign traceability fields such as `has_promotion_id`, `campaign_id`, `promotion_id`, `eligibility_decision`, `eligibility_reason`, `retail_request_id`, retry count, and resolution timestamps. [SRC-001]
- 202 ValidateCar FreeCharge precheck for vehicles without bound cards or with unpaid orders. [SRC-001]
- Separate FreeCharge zero-amount invoice mode. FreeCharge v1 skips invoice issuance entirely. [SRC-001, SRC-003]
- Dedicated retry metadata storage. v1 uses existing order timestamps for pending age and scheduler/job logs for retry evidence. [SRC-001, SRC-005]
- Charging-interval overlap or retroactive campaign adjustment when eligibility becomes active after the successful 202 ValidateCar `requestTime`. [SRC-007]

## Current Code Alignment Constraints

- Current order state is stored in `lxm_cpo_orders.status`, not `order_status`. [SRC-002]
- FreeCharge maps to existing `NoChargePromotion = 12`; pending requires a new `EligibilityPending` status. [SRC-002, SRC-003]
- Current duplicate checkout behavior returns `EC215`; SRC-005 confirms this must remain unchanged. [SRC-002, SRC-005]
- Current CPO timestamps are epoch-millisecond strings. Retail `charging_time` source is the successful 202 ValidateCar `requestTime`, converted to RFC3339 UTC only for the new Retail side-call. [SRC-002, SRC-004, SRC-005]
- Current 202 ValidateCar checks bound-card availability, card expiry, AutoCharge enabled status, and outstanding payments before charging starts. FreeCharge v1 preserves those checks and does not add a 202 FreeCharge precheck. [SRC-002]
- Current 202 outstanding-payment lookup checks existing `NoBoundCards`, `Unpaid`, and `FailedToPay` statuses. `EligibilityPending` must not be added to this or an equivalent 202 blocker list. [SRC-002, SRC-006]
- Retail eligibility reference time is not 203 `startTime`, 203 Checkout time, retry time, or charging interval overlap in v1. [SRC-004, SRC-007]

## Split Feature Decisions

| Spec Feature Slug | Decision | Rationale | Source |
|-------------------|----------|-----------|--------|
| autocharge-freecharge | Draft one Spec Kit input package for the checkout eligibility, status mapping, payment guard, invoice guard, reporting/redo guard, pending resolution behavior, and compatibility guards that preserve existing 202/203 HTTP contracts, prevent `EligibilityPending` from blocking future 202 requests, and keep the v1 eligibility reference fixed to successful 202 `requestTime`. | The source describes one coherent product feature centered on additive 203 Checkout FreeCharge handling, with codebase alignment constraints captured in SRC-002 and clarification decisions captured in SRC-003, SRC-004, SRC-005, SRC-006, and SRC-007. | SRC-001, SRC-002, SRC-003, SRC-004, SRC-005, SRC-006, SRC-007 |
| autocharge-freecharge-traceability | Deferred future feature if campaign traceability becomes required. | Trace table and campaign fields are explicitly deferred from the current version. | SRC-001 |
| autocharge-freecharge-202-precheck | Deferred future feature if business requires FreeCharge validation before charging starts. | Source states 202 is not the formal FreeCharge decision point in this version. | SRC-001 |
| autocharge-freecharge-retroactive-eligibility | Deferred future feature if business requires charging-interval overlap or retroactive campaign adjustment. | SRC-007 fixes v1 eligibility to successful 202 ValidateCar `requestTime`; post-202 eligibility activation is out of scope. | SRC-007 |

## Cross-Feature Dependencies And Handoff Order

| Dependency | Owner | Handoff Impact | Source |
|------------|-------|----------------|--------|
| Retail FreeCharge eligibility API | Retail | AutoCharge cannot complete eligibility behavior without confirmed API availability, timeout expectations, and response handling. | SRC-001, SRC-005 |
| Existing AutoCharge 202/203 CPO flow | AutoCharge | Feature must preserve current request-log semantics, HTTP contracts, duplicate behavior, and non-FreeCharge checkout behavior. | SRC-001, SRC-005 |
| Existing 202 ValidateCar blocker rules | AutoCharge | Existing bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment checks remain unchanged; `EligibilityPending` must not be treated as an outstanding-payment blocker for future charging sessions. | SRC-002, SRC-006 |
| Existing payment flow | AutoCharge and payment provider integration | Payment must start only for final status `Unpaid`; helper and redo entry points need explicit FreeCharge/pending guards. | SRC-001, SRC-002 |
| Existing invoice flow | AutoCharge, Finance/Tax | Invoice issuance must not run for FreeCharge or pending statuses; zero-amount invoice mode is out of scope for v1. | SRC-001, SRC-002, SRC-003 |
| Operations or scheduler mechanism | AutoCharge operations | Pending resolution follows SRC-005 retry interval, threshold, warning, manual recovery, and evidence-source decisions. | SRC-001, SRC-005 |

## Decision Rationale

- The FreeCharge decision belongs in 203 Checkout because that is where CPO orders are created and payment/invoice decisions are made. [SRC-001]
- 202 ValidateCar remains a pre-charge validation flow and cannot be the final FreeCharge decision point in the current version. [SRC-001]
- Retail remains the source of truth for eligibility, so AutoCharge only consumes an eligibility decision and controls order status, payment, and invoice behavior. [SRC-001]
- The current version is intentionally minimal: order-level status and control-flow behavior are in scope; campaign traceability persistence is deferred. [SRC-001]
- The compatibility constraint is central: FreeCharge is an additive AutoCharge campaign behavior and must not change existing 202/203 HTTP contracts or existing non-FreeCharge behavior. [SRC-005]
- The current 202 card-validation boundary is preserved because FreeCharge v1 does not include a pre-charge Retail eligibility check that could safely replace existing bound-card and expiry checks. [SRC-002]
- `EligibilityPending` protects users from premature payment/invoice while Retail is unavailable; it must not become a customer charging-denial state for later 202 ValidateCar requests. [SRC-006]
- The v1 `charging_time` rule is intentionally point-in-time based. It avoids ambiguous charging interval and retroactive campaign decisions until PO/TPM explicitly reopens that scope. [SRC-007]
