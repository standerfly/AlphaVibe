# Extracted Requirements: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12

## Source Map

| Source ID | Source |
|-----------|--------|
| SRC-001 | raw/autocharge_freecharge_spec.md |
| SRC-002 | raw/src-002-autocharge-freecharge-codebase-alignment.md |
| SRC-003 | raw/src-003-clarification-answers-2026-05-12.md |
| SRC-004 | raw/src-004-clarification-answers-2026-05-12-charging-time.md |
| SRC-005 | raw/src-005-clarification-answers-2026-05-12-contract-and-retry.md |
| SRC-006 | raw/src-006-clarification-answers-2026-05-12-eligibility-pending-202.md |
| SRC-007 | raw/src-007-clarification-answers-2026-05-12-mid-session-eligibility.md |

## Candidate Functional Requirements

| Requirement ID | Candidate Requirement | Source |
|----------------|-----------------------|--------|
| FR-001 | AutoCharge shall preserve existing 202 ValidateCar behavior: create a `lxm_cpo_request_logs` record with `api_type = 202`, run existing validations including bound-card availability, card expiry, AutoCharge-enabled status, and outstanding-payment checks, and not create CPO orders, trigger payment, or trigger invoice. | SRC-001, SRC-002 |
| FR-002 | AutoCharge shall preserve existing 203 Checkout entry behavior and HTTP contract: create a `lxm_cpo_request_logs` record with `api_type = 203`, validate payload and duplicates, parse checkout fields, build an order object, enrich owner, vehicle, and card data from the 202 log or fallback lookup, and keep the current request path, required fields, timestamp semantics, response code meanings, response body shape, and duplicate behavior. | SRC-001, SRC-005 |
| FR-003 | AutoCharge shall resolve `vehicle_id` as the vehicle UUID before calling the Retail FreeCharge eligibility API. VIN, `car_no`, and `carId` may only be internal lookup inputs and shall not be sent as `vehicle_id`. | SRC-001 |
| FR-004 | For valid 203 Checkout requests with `amount > 0`, no duplicate order, and usable eligibility inputs from the successful 202 ValidateCar request log, AutoCharge shall call `GET /promotion/api/v1/freecharge/eligibility` before finalizing the order as `Unpaid` and before payment starts. | SRC-001, SRC-004 |
| FR-005 | The Retail eligibility request shall include `vehicle_id` and `charging_time`. `vehicle_id` is the vehicle UUID, and `charging_time` is an RFC3339 UTC string derived from the successful 202 ValidateCar request log `requestTime`, not 203 `startTime`. Existing CPO/LXM timestamp fields remain epoch-millisecond strings. | SRC-001, SRC-004, SRC-005 |
| FR-006 | If Retail returns `eligible = true`, AutoCharge shall create the CPO order with the existing `NoChargePromotion` status as the FreeCharge physical status, skip payment, skip ECPay payment/capture calls, and skip invoice issuance. | SRC-001, SRC-002, SRC-003 |
| FR-007 | If Retail returns `eligible = false`, AutoCharge shall continue existing 203 checkout order-status logic; only a final status of `Unpaid` may start payment. | SRC-001 |
| FR-008 | If the Retail eligibility API times out, returns 5xx, is unavailable, fails network connection, or returns an unparsable response, AutoCharge shall create the order with a new `EligibilityPending` status, block payment and invoice, and retry later. The synchronous 203 Checkout timeout is 3 seconds with no inline retry. | SRC-001, SRC-002, SRC-003, SRC-005 |
| FR-008A | If AutoCharge cannot use the successful 202 ValidateCar request log for Retail eligibility inputs, including missing 202 log, missing `requestTime`, unparsable `requestTime`, or unavailable vehicle UUID, AutoCharge shall create the order with `EligibilityPending`, block payment and invoice, and retry or reconcile later. | SRC-004 |
| FR-008B | If Retail returns 4xx caused by missing or invalid vehicle UUID, AutoCharge shall create `EligibilityPending`, block payment and invoice, alert for recovery, and shall not treat the response as not eligible or fall back to normal payment. | SRC-005 |
| FR-009 | If `amount == 0`, AutoCharge shall preserve the existing `NoCharge` behavior and does not need to call Retail eligibility. Negative amounts are invalid input under the current 203 Checkout DTO validation. | SRC-001, SRC-002 |
| FR-010 | Payment shall start only when order status is `Unpaid`; all other statuses, including `NoChargePromotion` as FreeCharge, new `EligibilityPending`, `NoCharge`, `OwnerNotFound`, `NoBoundCards`, and `Paid`, shall be ignored or rejected by every payment-capable entry point, including 203 Checkout, redo flows, and payment helper functions. | SRC-001, SRC-002, SRC-003 |
| FR-011 | Invoice issuance shall not run for `NoChargePromotion` as FreeCharge, new `EligibilityPending`, `NoCharge`, `OwnerNotFound`, or `NoBoundCards`. | SRC-001, SRC-002, SRC-003 |
| FR-012 | Duplicate 203 Checkout requests by `requestId` or by `carId + startTime + endTime` shall preserve current duplicate behavior by returning `EC215`, shall not create duplicate CPO orders, and shall not repeat Retail eligibility calls. | SRC-001, SRC-002, SRC-005 |
| FR-013 | Pending resolution shall retry orders with the new `EligibilityPending` status every 5 minutes, stop after 12 attempts or 60 minutes pending age, update the existing CPO order, and never insert a new order for the retry. | SRC-001, SRC-002, SRC-003, SRC-005 |
| FR-014 | Pending resolution shall set an order to `NoChargePromotion` when retry finds eligibility, or continue existing checkout status logic when retry finds non-eligibility and enough data exists. | SRC-001, SRC-002, SRC-003 |
| FR-015 | AutoCharge shall not create a FreeCharge trace table or persist campaign traceability fields in the current version. The minimum data change is support for new `EligibilityPending` in `lxm_cpo_orders.status`; FreeCharge uses existing `NoChargePromotion`. | SRC-001, SRC-002, SRC-003 |
| FR-016 | AutoCharge shall alert and mark reconciliation required if a FreeCharge or pending order enters payment or invoice issuance. Existing abnormal reports must be extended because they do not currently detect this leakage explicitly. | SRC-001, SRC-002, SRC-003 |
| FR-017 | FreeCharge is an additive AutoCharge campaign behavior and shall not change the existing CPO/LXM 202 ValidateCar or 203 Checkout HTTP contract or existing non-FreeCharge behavior. | SRC-005 |
| FR-018 | An existing `EligibilityPending` FreeCharge order shall not block future 202 ValidateCar requests and shall not be treated as unpaid debt, failed payment, outstanding payment, or any equivalent 202 pre-charge blocker. | SRC-006 |
| FR-019 | AutoCharge shall evaluate FreeCharge eligibility using the successful 202 ValidateCar `requestTime` only and shall not retroactively grant FreeCharge when eligibility becomes active after that time in v1. | SRC-007 |

## Candidate Actors And User Goals

| Actor | Goal | Source |
|-------|------|--------|
| CPO/LXM | Send existing 202 ValidateCar and 203 Checkout requests without changed paths, required fields, timestamp semantics, response codes, response body shape, duplicate behavior, or `api_type = 202` / `api_type = 203` meaning. | SRC-001, SRC-005 |
| AutoCharge Service | Decide payment and invoice behavior at 203 Checkout based on Retail eligibility while preserving existing checkout behavior. | SRC-001 |
| Retail Service | Remain the source of truth for FreeCharge eligibility and provide the AutoCharge-facing eligibility API. | SRC-001 |
| Payment Flow | Charge only orders whose final status is `Unpaid`. | SRC-001 |
| Invoice Flow | Issue invoices only for eligible paid normal orders; FreeCharge and pending orders shall not issue invoices. | SRC-001, SRC-003 |
| Operations or Support | Detect and recover payment, invoice, and pending-resolution leakage or stuck states. | SRC-001 |
| Finance or Tax | Review the v1 decision that FreeCharge skips invoice issuance entirely if governance requires confirmation. | SRC-003 |

## Candidate Success Criteria

- 202 ValidateCar keeps creating only request logs and never creates orders, payments, or invoices. [SRC-001]
- Existing 202 ValidateCar bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment blocker behavior remains unchanged. [SRC-002]
- 203 Checkout remains the FreeCharge decision point and preserves existing duplicate, validation, request, and response contract behavior. [SRC-001, SRC-005]
- Eligible positive-amount orders are stored as `NoChargePromotion` and do not trigger payment or invoice issuance. [SRC-001, SRC-002, SRC-003]
- Not-eligible positive-amount orders follow existing checkout status logic and only `Unpaid` starts payment. [SRC-001]
- Retail eligibility failures create orders with new `EligibilityPending`, block payment and invoice, and are retried against the existing order. [SRC-001, SRC-002, SRC-003]
- Missing or unusable successful 202 ValidateCar eligibility inputs create `EligibilityPending` and do not enter payment or invoice issuance. [SRC-004]
- Zero-amount orders remain `NoCharge` and do not require a Retail eligibility query; negative amount is invalid input. [SRC-001, SRC-002]
- Missing vehicle UUID does not result in a FreeCharge order or an invalid Retail eligibility call. [SRC-001]
- Duplicate checkout requests do not create duplicate orders or duplicate Retail checks and preserve `EC215`. [SRC-002, SRC-005]
- Payment and invoice guard failures raise alerts and require reconciliation. [SRC-001]
- Existing non-FreeCharge 202/203 behavior remains unchanged. [SRC-005]
- A prior `EligibilityPending` FreeCharge order does not prevent a later 202 ValidateCar from passing when existing non-FreeCharge validation rules pass. [SRC-006]
- Mid-session or post-202 eligibility activation does not retroactively change v1 FreeCharge outcome. [SRC-007]

## Candidate Constraints And Assumptions

- Retail, not AutoCharge, determines FreeCharge eligibility. [SRC-001]
- AutoCharge must not infer eligibility from order type, vehicle model, amount, DMS f16, card status, owner type, 202 success or failure, VIN, or `car_no`. [SRC-001]
- Existing credit-card boundaries remain unchanged: 202 checks bound-card availability and card expiry before charging starts; live ECPay authorization happens later only for `Unpaid` orders; authorization failure keeps the existing `FailedToPay` behavior. [SRC-002]
- `api_type = 202` and `api_type = 203` remain request-log flow markers and are not order statuses. [SRC-001]
- FreeCharge and pending are order-level logical decisions stored in the current `lxm_cpo_orders.status` field. FreeCharge maps to the existing `NoChargePromotion` status; pending requires a new `EligibilityPending` status. [SRC-001, SRC-002, SRC-003]
- The current codebase already has `LxmCpoOrderStatusNoChargePromotion = 12`, but does not have an `EligibilityPending` enum value. [SRC-002, SRC-003]
- Current CPO/LXM 202/203 timestamp fields remain epoch-millisecond strings. Retail `charging_time` source is the successful 202 ValidateCar request log `requestTime`; 203 `startTime` remains the order charging start time and duplicate-check input, not the FreeCharge eligibility reference time. Retail `charging_time` wire format is RFC3339 UTC. [SRC-002, SRC-004, SRC-005]
- The current version does not persist FreeCharge traceability fields or create a trace table. [SRC-001]
- FreeCharge v1 shall not trigger payment deduction and shall not issue an invoice. A separate zero-amount invoice mode is out of scope unless PO/TPM reopens the decision. [SRC-003]
- Retry count and retry history are not stored in a dedicated FreeCharge trace table in the current version. Pending age uses existing order timestamps, and retry evidence uses scheduler/job logs linked by `order_id` and `request_id`. [SRC-001, SRC-005]
- FreeCharge is additive to AutoCharge and must not change existing 202/203 HTTP contracts or existing non-FreeCharge behavior. [SRC-005]
- `EligibilityPending` is not an outstanding-payment or unpaid-debt state for 202 ValidateCar. It is an operations/retry recovery state. [SRC-006]
- v1 eligibility reference time is fixed to successful 202 ValidateCar `requestTime`; charging-interval overlap, mid-session activation, 203 Checkout time, retry time, and post-202 campaign qualification changes are out of scope. [SRC-007]

## Candidate Error Or Failure Behavior

| Failure Case | Expected Behavior | Source |
|--------------|-------------------|--------|
| Retail timeout, network error, 5xx, connection refused, parse failure, or temporary unavailability | Create new `EligibilityPending`, block payment and invoice, and retry later. The synchronous 203 Checkout Retail timeout is 3 seconds with no inline retry. | SRC-001, SRC-002, SRC-003, SRC-005 |
| Missing successful 202 ValidateCar log, missing 202 `requestTime`, unparsable 202 `requestTime`, or unavailable vehicle UUID from 202 eligibility inputs | Create new `EligibilityPending`, block payment and invoice, and retry or reconcile later. | SRC-004 |
| Retail 4xx caused by missing or invalid vehicle UUID | Create `EligibilityPending`, block payment and invoice, alert for recovery, and do not treat as not eligible or continue to payment. | SRC-005 |
| Missing vehicle UUID before Retail call | Do not call Retail, do not mark FreeCharge, and create `EligibilityPending` when required eligibility inputs cannot be derived from the successful 202 ValidateCar log. | SRC-001, SRC-004 |
| Existing `EligibilityPending` from a prior FreeCharge order when later 202 ValidateCar is called | Do not block 202 solely because of `EligibilityPending`; process 202 using existing validation rules. | SRC-006 |
| Vehicle becomes eligible after the successful 202 ValidateCar `requestTime` | Do not retroactively grant FreeCharge in v1; evaluate eligibility using the successful 202 reference time only. | SRC-007 |
| Payment leakage for FreeCharge or pending status | Raise alert, stop payment if possible, and mark reconciliation required. | SRC-001, SRC-002 |
| Invoice leakage for FreeCharge or pending status | Raise alert, stop invoice if possible, and mark reconciliation required. | SRC-001, SRC-002, SRC-003 |
| Duplicate checkout | Preserve current behavior by returning `EC215`, avoid duplicate order creation, and do not repeat Retail call. | SRC-001, SRC-002, SRC-005 |

## Duplicates, Conflicts, And Unclear Statements

| Item | Classification | Notes | Source |
|------|----------------|-------|--------|
| Physical values for `FreeCharge` and `EligibilityPending` | Answered for product baseline | FreeCharge maps to existing `NoChargePromotion`; `EligibilityPending` shall be added as a new status. The exact numeric value can be assigned during implementation unless TPM requires a specific value. | SRC-001, SRC-002, SRC-003 |
| Existing `NoChargePromotion` status | Resolved | Product decision is to treat `NoChargePromotion` as FreeCharge for this feature. Current app-facing promotion copy, redo exclusions, and status-list APIs still need implementation review. | SRC-002, SRC-003 |
| Retail timeout and retry policy | Answered | 203 Checkout timeout is 3 seconds without inline retry. Pending retry runs every 5 minutes and stops after 12 attempts or 60 minutes. Warning starts at 30 minutes; manual recovery starts at 60 minutes or 12 failures. | SRC-005 |
| Invoice policy | Answered | FreeCharge v1 skips payment deduction and invoice issuance; no zero-amount invoice mode is included in v1. | SRC-003 |
| Charging time source and format | Answered | Source is successful 202 ValidateCar request log `requestTime`; 203 `startTime` is not used for eligibility. Retail wire format is RFC3339 UTC. Existing CPO/LXM timestamp fields remain epoch-millisecond strings. | SRC-001, SRC-002, SRC-004, SRC-005 |
| Missing successful 202 eligibility inputs | Answered for product baseline | If AutoCharge cannot use the successful 202 log for eligibility inputs, the order enters `EligibilityPending` and does not enter payment or invoice issuance. | SRC-004 |
| Missing or invalid vehicle UUID handling | Answered | Missing vehicle UUID before the Retail call enters `EligibilityPending`; Retail 4xx caused by invalid vehicle UUID also enters `EligibilityPending`, blocks payment and invoice, and alerts for recovery. | SRC-001, SRC-004, SRC-005 |
| CPO/LXM response mapping | Answered | FreeCharge and `EligibilityPending` preserve current 203 Checkout success contract: HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`. | SRC-005 |
| Duplicate checkout response | Answered | Current implementation returns `EC215`, and SRC-005 confirms duplicate checkout must preserve `EC215`. | SRC-002, SRC-005 |
| Pending order impact on later 202 | Answered | Existing `EligibilityPending` FreeCharge orders do not block later 202 ValidateCar requests and must not be treated as unpaid debt or outstanding payment. | SRC-006 |
| Mid-session or post-202 eligibility activation | Deferred | If a vehicle becomes eligible after the successful 202 ValidateCar `requestTime`, v1 does not retroactively grant FreeCharge. Charging-interval overlap, 203 Checkout time, retry time, and retroactive campaign adjustment are deferred. | SRC-007 |
| Existing credit-card validation boundary | Answered | Current 202 ValidateCar checks bound-card availability and card expiry before charging starts. Live card authorization happens later for `Unpaid` orders. FreeCharge v1 preserves this boundary and does not add a 202 precheck to bypass existing card or outstanding-payment blockers. | SRC-002 |
| Status field name | Current-code mismatch | SRC-001 uses `order_status`; current code/model uses `lxm_cpo_orders.status`. | SRC-002 |
| 202 FreeCharge precheck | Deferred | Current version excludes formal FreeCharge decision in 202; future behavior may be needed if FreeCharge vehicles can start without card or with unpaid orders. | SRC-001 |
| FreeCharge traceability | Deferred | Trace table and campaign fields are explicitly deferred. | SRC-001 |
