# Product Spec: AutoCharge FreeCharge

**Status:** In Review
**Feature Slug:** autocharge-freecharge
**Function Branch:** function/autocharge-freecharge
**Product Owner:** joe-yf-lin
**TPM:** joe-yf-lin
**Accepted At:** N/A
**Acceptance Evidence:** N/A - pending explicit PO/TPM acceptance of this product spec, supporting artifacts, and Spec Kit input split

## Problem And Goal

AutoCharge must support a FreeCharge campaign in which Retail is the source of truth for eligibility. For eligible positive-amount CPO checkout orders, AutoCharge must waive payment and invoice issuance while preserving the existing 202 ValidateCar and 203 Checkout HTTP contracts and preserving existing non-FreeCharge behavior.

The goal is to add FreeCharge as an additive AutoCharge campaign behavior at the 203 Checkout order decision point, without changing existing CPO/LXM request paths, required fields, timestamp semantics, response code meanings, response body shape, duplicate behavior, or non-FreeCharge processing.

## Business Context And Priority

- Priority: P0 / launch-blocking for the planned FreeCharge campaign. [SRC-005]
- Timing: Target stage deployment on 2026-06-10. [SRC-003]
- Business value: eligible positive-amount AutoCharge sessions can be treated as campaign no-charge orders without collecting payment or issuing invoices, while ineligible sessions continue through the existing checkout and payment path. [SRC-001, SRC-003, SRC-005]

## Actors

- CPO/LXM: sends the existing 202 ValidateCar and 203 Checkout requests and receives the existing response contract. [SRC-001, SRC-005]
- AutoCharge Service: calls Retail during 203 Checkout, stores the final order status, and controls payment and invoice entry points. [SRC-001]
- Retail: owns FreeCharge eligibility and exposes the AutoCharge-facing eligibility API. [SRC-001]
- Payment Flow: charges only orders whose final status is `Unpaid`. [SRC-001, SRC-002]
- Invoice Flow: issues invoices only through the normal paid flow; FreeCharge and pending orders do not issue invoices in v1. [SRC-003]
- Operations: monitors payment leakage, invoice leakage, and stuck `EligibilityPending` orders. [SRC-002, SRC-005]

## MVP Scope

### In Scope

- Preserve existing 202 ValidateCar behavior and HTTP contract, including existing bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment checks. 202 remains a request-log validation flow and is not the formal FreeCharge decision point. [SRC-001, SRC-002, SRC-005]
- Preserve existing 202 ValidateCar blocker rules. A prior `EligibilityPending` FreeCharge order must not block future 202 ValidateCar requests and must not be treated as unpaid debt, failed payment, or outstanding payment. [SRC-006]
- Preserve existing 203 Checkout HTTP contract, including request path, required fields, epoch-millisecond CPO timestamp fields, HTTP status behavior, response body shape, response code meanings, and duplicate `EC215` behavior. [SRC-002, SRC-005]
- During valid positive-amount 203 Checkout, call Retail eligibility before finalizing an order as `Unpaid` and before payment starts. [SRC-001]
- Use Retail as the only FreeCharge eligibility source; AutoCharge must not infer eligibility from order type, vehicle model, amount, DMS data, card status, owner type, 202 result, VIN, or `car_no`. [SRC-001]
- Send Retail `vehicle_id` as the vehicle UUID resolved from successful 202 eligibility inputs, never VIN, `car_no`, or `carId`. [SRC-001, SRC-004]
- Send Retail `charging_time` as an RFC3339 UTC string derived from the successful 202 ValidateCar request log `requestTime`. [SRC-004, SRC-005]
- Store Retail eligible orders as existing `NoChargePromotion` and skip payment and invoice issuance. [SRC-002, SRC-003]
- Store Retail failure, timeout, invalid-vehicle 4xx, or unusable 202 eligibility input cases as new `EligibilityPending`, block payment and invoice, and retry or manually recover later. [SRC-004, SRC-005]
- Continue existing checkout status logic for Retail `eligible = false`; payment may start only if the final status is `Unpaid`. [SRC-001]
- Add guards so `NoChargePromotion`, `EligibilityPending`, and other non-`Unpaid` statuses cannot enter payment or invoice through checkout, helper functions, redo flows, or scheduled jobs. [SRC-002]

### Out Of Scope

- Changing the existing 202 ValidateCar or 203 Checkout HTTP contract. [SRC-005]
- Changing existing non-FreeCharge checkout behavior. [SRC-005]
- Retail eligibility creation, Retail `has_promotions`, DMS sales category checks, remote-control activation events, or offline manual eligibility import. [SRC-001]
- App promotion display changes owned by Retail or APP. [SRC-001]
- AutoCharge FreeCharge trace table or dedicated campaign traceability fields in v1. [SRC-001, SRC-005]
- Separate zero-amount invoice mode for FreeCharge v1. [SRC-003]
- Retroactive FreeCharge grant when eligibility becomes active after the successful 202 ValidateCar `requestTime`. [SRC-007]
- Charging-interval overlap, mid-session eligibility activation, 203 Checkout time, or retry-time campaign qualification as eligibility references. [SRC-007]

### Deferred

- 202 FreeCharge precheck before charging starts. [SRC-001]
- Dedicated FreeCharge traceability storage and retry metadata fields. [SRC-001, SRC-005]
- Future FreeCharge zero-amount invoice mode if Finance/Tax later requires it. [SRC-003]
- Future support for retroactive campaign adjustment or eligibility evaluation across the charging interval. [SRC-007]

## Functional Requirements

- FR-001: AutoCharge shall preserve 202 ValidateCar behavior and HTTP contract, including existing bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment checks; it creates request logs and does not create orders, payments, or invoices. [SRC-001, SRC-002, SRC-005]
- FR-002: AutoCharge shall preserve 203 Checkout HTTP contract and existing validation/duplicate behavior, including `EC215` for duplicates. [SRC-002, SRC-005]
- FR-003: AutoCharge shall call Retail eligibility only for valid, non-duplicate, positive-amount 203 Checkout orders with usable 202 eligibility inputs. [SRC-001, SRC-004]
- FR-004: If Retail returns `eligible = true`, AutoCharge shall create the order as `NoChargePromotion`, return the existing checkout success contract, and skip payment and invoice. [SRC-001, SRC-003, SRC-005]
- FR-005: If Retail returns `eligible = false`, AutoCharge shall continue existing checkout status logic and only start payment for final status `Unpaid`. [SRC-001]
- FR-006: If Retail times out, returns 5xx, has a network or parse failure, returns invalid-vehicle 4xx, or if 202 eligibility inputs are unusable, AutoCharge shall create `EligibilityPending`, return the existing checkout success contract, and block payment and invoice. [SRC-004, SRC-005]
- FR-007: `EligibilityPending` retry shall run every 5 minutes and stop after 12 attempts or 60 minutes pending age, whichever comes first. [SRC-005]
- FR-008: Operations shall receive warning evidence after 30 minutes pending age and manual recovery evidence after 60 minutes or 12 failed retry attempts. [SRC-005]
- FR-009: `data.amount` in the CPO/LXM 203 Checkout response shall remain the original checkout amount for FreeCharge and pending cases. Payment bypass is represented internally by status and guards, not by changing the external amount to zero. [SRC-005]
- FR-010: An existing `EligibilityPending` FreeCharge order shall not block future 202 ValidateCar requests. AutoCharge shall not add `EligibilityPending` to 202 outstanding-payment, unpaid-debt, failed-payment, or equivalent blocker logic. [SRC-006]
- FR-011: AutoCharge shall evaluate FreeCharge eligibility using the successful 202 ValidateCar `requestTime` only and shall not retroactively grant FreeCharge when eligibility becomes active after that time in v1. [SRC-007]

## Acceptance Scenarios

1. Given an existing 202 ValidateCar request, when the request is processed, then AutoCharge preserves the current request and response contract, existing card-validation behavior, and existing blocker rules, and does not create an order, payment, or invoice. [SRC-001, SRC-002, SRC-005]
2. Given a valid positive-amount 203 Checkout and Retail returns `eligible = true`, when AutoCharge creates the order, then status is `NoChargePromotion`, payment and invoice are skipped, and CPO/LXM receives the existing success response contract with original `data.amount`. [SRC-003, SRC-005]
3. Given a valid positive-amount 203 Checkout and Retail returns `eligible = false`, when AutoCharge creates the order, then existing checkout status logic applies and payment starts only for `Unpaid`. [SRC-001]
4. Given Retail timeout, 5xx, network failure, parse failure, invalid-vehicle 4xx, or unusable successful 202 eligibility inputs, when AutoCharge creates the order, then status is `EligibilityPending`, payment and invoice are blocked, and CPO/LXM receives the existing success response contract. [SRC-004, SRC-005]
5. Given a customer has a previous `EligibilityPending` FreeCharge order because Retail was unavailable, when the customer starts another charging session and calls 202 ValidateCar, then AutoCharge processes 202 using existing validation rules and does not reject the request solely due to the pending FreeCharge order. [SRC-006]
6. Given a vehicle becomes FreeCharge-eligible only after the successful 202 ValidateCar `requestTime`, when AutoCharge evaluates the later 203 Checkout, then v1 does not retroactively grant FreeCharge solely because eligibility changed after the 202 reference time. [SRC-007]
7. Given a duplicate 203 Checkout, when AutoCharge detects duplicate `requestId` or `carId + startTime + endTime`, then it preserves the current `EC215` behavior and does not call Retail again. [SRC-002, SRC-005]
8. Given any FreeCharge or pending order, when payment, invoice, redo, or scheduled job entry points evaluate it, then they do not create payment or invoice records and produce recovery evidence if leakage is detected. [SRC-002, SRC-005]

## Success Criteria

- Existing 202/203 HTTP contract compatibility is preserved for CPO/LXM integrations. [SRC-005]
- Existing 202 ValidateCar charging continuity is preserved when a prior FreeCharge order is stuck in `EligibilityPending`. [SRC-006]
- Existing non-FreeCharge 203 behavior is unchanged except for the additive Retail eligibility side-call on eligible positive-amount checkout candidates. [SRC-005]
- Eligibility reference time remains stable and auditable: only successful 202 ValidateCar `requestTime` determines the Retail `charging_time` for v1. [SRC-004, SRC-005, SRC-007]
- Eligible positive-amount orders are stored as `NoChargePromotion` and never enter payment or invoice issuance. [SRC-003]
- Pending eligibility orders are stored as `EligibilityPending`, are retried against the existing order, and never enter payment or invoice before resolution. [SRC-005]
- Duplicate checkout still returns `EC215`. [SRC-002, SRC-005]
- Stuck pending, payment leakage, and invoice leakage are observable with operator recovery paths. [SRC-002, SRC-005]

## Constraints And Assumptions

- Retail is the source of truth for eligibility. [SRC-001]
- FreeCharge is additive to AutoCharge and must not change existing 202/203 HTTP contracts. [SRC-005]
- Existing credit-card validation boundaries remain unchanged: 202 checks bound-card availability and card expiry, live ECPay authorization happens only later for `Unpaid` orders, and FreeCharge v1 does not add a 202 precheck to bypass existing card or outstanding-payment blockers. [SRC-002]
- `EligibilityPending` is a pending FreeCharge recovery state, not an outstanding-payment blocker for future 202 ValidateCar requests. [SRC-006]
- Existing CPO/LXM timestamp fields remain epoch-millisecond strings; only the new Retail `charging_time` query value is converted to RFC3339 UTC. [SRC-002, SRC-005]
- v1 does not evaluate eligibility using charging-interval overlap, mid-session activation, 203 Checkout time, retry time, or campaign changes after successful 202 ValidateCar `requestTime`. [SRC-007]
- `NoChargePromotion = 12` is the selected FreeCharge physical status. [SRC-002, SRC-003]
- `EligibilityPending` is a new order status. Its exact numeric enum/database value may be assigned during implementation unless TPM later requires a specific value. [SRC-003]
- v1 does not add a FreeCharge trace table or retry metadata columns. [SRC-001, SRC-005]

## Dependencies

- Retail eligibility API availability and behavior. [SRC-001]
- Existing AutoCharge 202/203 request-log and checkout flow. [SRC-001, SRC-005]
- Current `lxm_cpo_orders.status` model and enum behavior. [SRC-002]
- Payment, invoice, redo, scheduler, reporting, and operations alerting paths. [SRC-002, SRC-005]

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| Retail timeout, network error, 5xx, temporary unavailable, or parse failure | Create `EligibilityPending`; block payment and invoice; preserve checkout success contract. | Request log and pending order evidence. | Retry every 5 minutes until 12 attempts or 60 minutes. | Yes |
| Retail 4xx caused by missing or invalid vehicle UUID | Create `EligibilityPending`; block payment and invoice; do not treat as not eligible. | Alert/manual recovery evidence. | Manual investigation or corrected retry path. | Yes |
| Missing successful 202 log, missing or unparsable 202 `requestTime`, or unavailable vehicle UUID | Create `EligibilityPending`; do not call Retail; block payment and invoice. | Pending order and missing-input evidence. | Retry or manual recovery using approved pending policy. | Yes |
| Existing `EligibilityPending` from a prior session when a later 202 ValidateCar is called | Do not treat the pending FreeCharge order as unpaid debt, failed payment, or outstanding payment; preserve existing 202 validation rules. | Normal 202 success or existing 202 error based on non-FreeCharge blockers only. | Continue pending retry/manual recovery separately. | Yes |
| Vehicle becomes eligible after successful 202 ValidateCar `requestTime` | Do not retroactively grant FreeCharge in v1; evaluate eligibility using the successful 202 reference time only. | Normal checkout outcome according to Retail evaluation at the 202 reference time. | Future scope if PO/TPM wants charging-interval or retroactive campaign adjustment. | No |
| FreeCharge or pending order enters payment | Payment leakage risk. | Alert and reconciliation evidence. | Stop payment if possible and investigate guard failure. | Yes |
| FreeCharge or pending order enters invoice issuance | Invoice leakage risk. | Alert and reconciliation evidence. | Stop invoice if possible and investigate guard failure. | Yes |
| Duplicate 203 Checkout | Preserve current `EC215`; do not create duplicate order; do not repeat Retail call. | Existing duplicate response contract. | No retry; duplicate behavior remains unchanged. | Yes |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Complete | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| Workflow Sequence | Yes | Complete | supporting-artifacts/workflow-sequence.md | Feature spans CPO/LXM, AutoCharge, Retail, payment, invoice, and operations |
| Order State Model | Yes | Complete | supporting-artifacts/order-state-model.md | `NoChargePromotion` and `EligibilityPending` affect order control flow |
| Retail API Contract | Yes | Complete | supporting-artifacts/retail-api-contract.md | New Retail eligibility side-call and preserved 202/203 contracts |
| Integration And Data Mapping | Yes | Complete | supporting-artifacts/integration-and-data-mapping.md | Vehicle/time mapping, timeout, retry, and failure semantics |
| Data Model Note | Yes | Complete | supporting-artifacts/data-model-note.md | Status mapping and deferred traceability decisions |
| Error Handling Matrix | Yes | Complete | supporting-artifacts/error-handling-matrix.md | Payment, invoice, duplicate, pending, and Retail failure handling |
| Observability And Recovery | Yes | Complete | supporting-artifacts/observability-recovery.md | Alert thresholds, retry evidence, and manual recovery |

## Source Decisions

- 2026-05-12: Target stage deployment is planned for 2026-06-10. [SRC-003]
- 2026-05-12: FreeCharge maps to existing `NoChargePromotion`; `EligibilityPending` shall be added as a new status. [SRC-003]
- 2026-05-12: FreeCharge shall not trigger payment deduction or invoice issuance in v1. [SRC-003]
- 2026-05-12: Retail `charging_time` source shall be successful 202 ValidateCar request log `requestTime`; unusable 202 eligibility inputs enter `EligibilityPending`. [SRC-004]
- 2026-05-12: Retail timeout, pending retry, alert thresholds, Retail 4xx handling, CPO/LXM response mapping, and 202/203 compatibility constraints are defined by SRC-005.
- 2026-05-12: Existing 202/203 HTTP contracts must not change; FreeCharge is additive and must not impact existing non-FreeCharge behavior. [SRC-005]
- 2026-05-12: Existing credit-card validation and authorization boundaries are preserved; FreeCharge v1 does not add a 202 FreeCharge precheck. [SRC-002]
- 2026-05-12: Existing `EligibilityPending` FreeCharge orders must not block future 202 ValidateCar requests or be treated as unpaid/outstanding payment. [SRC-006]
- 2026-05-12: Mid-session or post-202 eligibility activation is deferred; v1 evaluates eligibility only against successful 202 ValidateCar `requestTime`. [SRC-007]
