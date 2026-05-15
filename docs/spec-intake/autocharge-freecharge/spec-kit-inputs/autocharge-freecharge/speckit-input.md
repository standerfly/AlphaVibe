# Spec Kit Input: AutoCharge FreeCharge

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** autocharge-freecharge
**Handoff Order:** 1

## Feature Summary

Add FreeCharge as an additive AutoCharge campaign behavior during 203 Checkout. AutoCharge calls Retail for eligibility before positive-amount orders enter payment, stores eligible orders as `NoChargePromotion`, stores uncertain cases as `EligibilityPending`, blocks payment and invoice for both, and preserves existing CPO/LXM 202 ValidateCar and 203 Checkout HTTP contracts.

## Actors

- CPO/LXM: sends existing 202 ValidateCar and 203 Checkout requests and receives the existing response contract.
- AutoCharge Service: calls Retail, stores the final order status, and guards payment and invoice entry points.
- Retail: owns FreeCharge eligibility and provides the eligibility API.
- Payment Flow: charges only final `Unpaid` orders.
- Invoice Flow: issues invoices only through the normal paid flow.
- Operations: monitors and recovers payment leakage, invoice leakage, and stuck pending orders.

## Problem And Goal

AutoCharge needs to support a FreeCharge campaign for eligible positive-amount charging sessions without charging the user or issuing an invoice. The feature must not change existing 202/203 HTTP contracts or existing non-FreeCharge behavior.

## In Scope

- Preserve existing 202 ValidateCar behavior and HTTP contract, including existing bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment checks.
- Preserve existing 202 ValidateCar blocker rules; a prior `EligibilityPending` FreeCharge order must not block future 202 requests.
- Preserve existing 203 Checkout HTTP contract, including request path, required fields, timestamp field semantics, response code meanings, response body shape, and duplicate `EC215` behavior.
- Call Retail eligibility during valid, non-duplicate, positive-amount 203 Checkout before payment starts.
- Use vehicle UUID and RFC3339 UTC `charging_time` derived from successful 202 ValidateCar `requestTime` for the Retail side-call.
- Store Retail eligible orders as `NoChargePromotion`.
- Store Retail failures, invalid-vehicle 4xx, and unusable 202 eligibility inputs as `EligibilityPending`.
- Block payment and invoice for `NoChargePromotion` and `EligibilityPending` across checkout, helpers, redo flows, and scheduled jobs.
- Retry pending eligibility every 5 minutes until 12 attempts or 60 minutes pending age.
- Warn after 30 minutes pending age and require manual recovery after 60 minutes or 12 failed attempts.

## Out Of Scope

- Changing CPO/LXM 202 ValidateCar or 203 Checkout HTTP contracts.
- Changing non-FreeCharge 202/203 behavior.
- Retail eligibility creation, DMS eligibility logic, app promotion display, and offline eligibility import.
- FreeCharge trace table, campaign traceability fields, and dedicated retry metadata in v1.
- Retroactive FreeCharge grant when eligibility becomes active after successful 202 ValidateCar `requestTime`.
- Charging-interval overlap, mid-session eligibility activation, 203 Checkout time, retry time, or post-202 campaign qualification changes as v1 eligibility references.
- Separate zero-amount invoice mode for FreeCharge v1.
- 202 FreeCharge precheck before charging starts.

## User Scenarios

1. Existing CPO/LXM 202 and 203 callers continue using the same HTTP contract while AutoCharge adds FreeCharge behavior internally.
2. A positive-amount eligible checkout is stored as `NoChargePromotion`, returns the existing checkout success contract, and never enters payment or invoice.
3. A positive-amount ineligible checkout follows existing checkout status logic and can enter payment only if final status is `Unpaid`.
4. Retail timeout, Retail failure, invalid-vehicle 4xx, or unusable 202 eligibility input creates `EligibilityPending`, returns the existing checkout success contract, and waits for retry or manual recovery.
5. A customer with a prior `EligibilityPending` FreeCharge order can still pass a later 202 ValidateCar when existing non-FreeCharge validation rules pass.
6. A vehicle that becomes eligible after successful 202 ValidateCar `requestTime` does not receive a retroactive FreeCharge grant in v1.
7. Duplicate checkout returns `EC215`, creates no duplicate order, and does not call Retail again.
8. FreeCharge and pending orders are rejected by payment, invoice, redo, scheduler, and reporting entry points and produce recovery evidence if leakage is detected.

## Functional Requirements

- AutoCharge shall preserve existing 202 ValidateCar and 203 Checkout HTTP contracts.
- AutoCharge shall preserve existing 202 ValidateCar card-validation boundaries: bound-card availability and card expiry are still checked before charging starts, and FreeCharge v1 shall not add a 202 precheck that bypasses those existing blockers.
- AutoCharge shall treat FreeCharge as additive behavior that must not affect existing non-FreeCharge paths.
- AutoCharge shall call Retail only for valid, non-duplicate, positive-amount checkout candidates with usable 202 eligibility inputs.
- Retail `vehicle_id` shall be vehicle UUID, not VIN, `car_no`, or `carId`.
- Retail `charging_time` shall be RFC3339 UTC derived from successful 202 ValidateCar `requestTime`; existing CPO/LXM timestamp fields remain epoch-millisecond strings.
- v1 shall not evaluate eligibility using charging-interval overlap, mid-session activation, 203 Checkout time, retry time, or campaign qualification changes after successful 202 ValidateCar `requestTime`.
- Retail eligible orders shall use `NoChargePromotion`.
- Retail not-eligible orders shall continue existing checkout status logic.
- Retail timeout, 5xx, network error, parse failure, invalid-vehicle 4xx, and unusable 202 eligibility inputs shall create `EligibilityPending`.
- Existing `EligibilityPending` FreeCharge orders shall not be treated as unpaid debt, failed payment, outstanding payment, or any equivalent 202 blocker.
- `NoChargePromotion` and `EligibilityPending` shall not enter payment or invoice issuance.
- FreeCharge and `EligibilityPending` 203 responses shall preserve HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`.
- Duplicate checkout shall preserve `EC215` and shall not call Retail.

## Success Criteria

- Existing CPO/LXM 202/203 contract tests continue to pass unchanged.
- Existing 202 ValidateCar bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment blocker behavior remains unchanged.
- 202 ValidateCar is not rejected solely because the same customer has a prior `EligibilityPending` FreeCharge order.
- Mid-session or post-202 eligibility activation does not retroactively change the v1 FreeCharge outcome.
- Eligible positive-amount orders are stored as `NoChargePromotion` and have no payment or invoice records.
- Pending orders are stored as `EligibilityPending`, have no payment or invoice records, and retry according to the approved policy.
- Existing non-FreeCharge checkout outcomes remain compatible.
- Duplicate checkout still returns `EC215`.
- Payment leakage, invoice leakage, and stuck pending orders are observable and recoverable.

## Constraints And Assumptions

- Retail is the source of truth for FreeCharge eligibility.
- Current credit-card validation boundaries are unchanged: 202 checks bound card and expiry, and live ECPay authorization happens later only for `Unpaid` orders.
- v1 eligibility is point-in-time and uses successful 202 ValidateCar `requestTime` only.
- FreeCharge v1 skips payment deduction and invoice issuance entirely.
- `NoChargePromotion = 12` is the FreeCharge physical status.
- `EligibilityPending` is a new order status; its exact numeric value is an implementation detail unless TPM requires a specific value.
- `EligibilityPending` is an operations/retry recovery state, not a 202 outstanding-payment blocker.
- v1 does not add dedicated FreeCharge traceability or retry metadata storage.

## Dependencies

- Retail eligibility API: `GET /promotion/api/v1/freecharge/eligibility`.
- Existing AutoCharge 202 ValidateCar request logs, especially successful 202 vehicle UUID and `requestTime`.
- Existing AutoCharge 203 Checkout flow, duplicate detection, timestamp parsing, and order creation behavior.
- Current `lxm_cpo_orders.status` enum behavior, including existing `NoChargePromotion = 12` and new `EligibilityPending`.
- Payment flow, invoice flow, redo flows, scheduled jobs, abnormal reports, duplicate payment/invoice reports, and redo result emails.
- Operations or scheduler capability for pending retry, warning, manual recovery, and recovery evidence.

## Supporting Artifact Coverage

| Required Artifact Or Trait | Included Section | Status |
|----------------------------|------------------|--------|
| Multi-role, multi-system, or multi-step workflow | Workflow And Call Ordering | Included |
| Async job, callback, event handling, or state transition | Order State And Idempotency | Included |
| New or changed external/internal API behavior | API Contract Summary; Non-Call And No-Change Constraints | Included |
| Third-party or cross-system integration | Integration, Timeout, Retry, And Data Mapping | Included |
| New or changed data lifecycle | Data Model And Compatibility | Included |
| Security, privacy, compliance, or audit concern | Error Handling Matrix; Observability And Recovery | Included |
| High-risk, irreversible, payment, order, or control flow | Order State And Idempotency; Error Handling Matrix | Included |
| Operationally sensitive behavior | Observability And Recovery | Included |

## API Contract Summary

### CPO/LXM Compatibility

- Existing 202 ValidateCar and 203 Checkout request paths, required fields, timestamp field semantics, HTTP status behavior, response code meanings, response body shape, and duplicate behavior must remain unchanged.
- 202 ValidateCar remains `POST /ext/lxm-cpo/api/v1/validate/car` and creates only a request log with `api_type = 202`.
- 203 Checkout remains `POST /ext/lxm-cpo/api/v1/checkout` and creates a request log with `api_type = 203`.
- FreeCharge and `EligibilityPending` 203 responses preserve the existing success contract: HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`.
- Duplicate 203 Checkout preserves `EC215` and does not call Retail again.

### Retail Eligibility Side-Call

```http
GET /promotion/api/v1/freecharge/eligibility
```

| Parameter | Required | AutoCharge Source | Rules |
|-----------|----------|-------------------|-------|
| `vehicle_id` | Yes | Vehicle UUID from the successful 202 ValidateCar request log, or equivalent successful 202 eligibility input | Must be vehicle UUID. Must not be VIN, `car_no`, or `carId`. If unavailable, do not call Retail and create `EligibilityPending`. |
| `charging_time` | Yes | Successful 202 ValidateCar request log `requestTime` | Parse the existing CPO/LXM epoch-millisecond string and send RFC3339 UTC. Do not use 203 `startTime`, 203 Checkout time, retry time, charging-interval overlap, or mid-session activation. |

### Retail Outcomes

| Retail Outcome | AutoCharge Behavior |
|----------------|---------------------|
| `eligible = true` | Create the CPO order with `NoChargePromotion`, skip payment, skip invoice, and do not persist campaign traceability fields in v1. |
| `eligible = false` | Continue existing 203 checkout status logic; payment may start only if final status is `Unpaid`. |
| Timeout, network error, 5xx, temporary unavailable, or parse failure | Create `EligibilityPending`, block payment and invoice, preserve the existing 203 success contract, and retry later. |
| Retail 4xx caused by missing or invalid `vehicle_id` | Create `EligibilityPending`, block payment and invoice, alert for recovery, and do not treat as not eligible or continue to payment. |

- Synchronous 203 Checkout Retail timeout is 3 seconds with no inline retry.

## Integration, Timeout, Retry, And Data Mapping

| Area | Requirement |
|------|-------------|
| AutoCharge Service | Calls Retail during 203 Checkout, decides CPO order status, controls payment and invoice flow, and preserves existing CPO/LXM 202/203 HTTP contracts. |
| Retail | Owns FreeCharge eligibility creation and returns the AutoCharge-facing eligibility decision. |
| Payment Flow | Charges only final `Unpaid` orders. `NoChargePromotion` and `EligibilityPending` must not enter payment. |
| Invoice Flow | Issues invoices only through normal paid flow. FreeCharge and pending orders do not issue invoices in v1. |
| Operations or Scheduler | Retries `EligibilityPending` orders and alerts on leakage or stuck pending records. |

| Retail Field | AutoCharge Source | Product Rule |
|--------------|-------------------|--------------|
| `vehicle_id` | Vehicle UUID from successful 202 ValidateCar request log, or equivalent successful 202 eligibility input | Required. Must be vehicle UUID. If unavailable, do not call Retail and create `EligibilityPending`. |
| `charging_time` | Successful 202 ValidateCar request log `requestTime` | Required. Convert epoch-millisecond string to RFC3339 UTC for Retail. Existing CPO/LXM timestamp fields remain unchanged. |

- Retail timeout is 3 seconds in synchronous 203 Checkout with no inline retry.
- Pending retry runs every 5 minutes and stops after 12 attempts or 60 minutes pending age, whichever comes first.
- Warning starts after 30 minutes pending age.
- Manual recovery starts after 60 minutes pending age or 12 failed retry attempts.
- v1 does not add a FreeCharge trace table; retry evidence uses existing order timestamps and scheduler/job logs linked by `order_id` and `request_id`.

## Workflow And Call Ordering

- 202 ValidateCar creates a request log, runs existing validation, and does not create orders, payments, or invoices.
- 202 ValidateCar keeps existing bound-card, card-expiry, AutoCharge-enabled, and outstanding-payment checks.
- A prior `EligibilityPending` FreeCharge order shall not block a later 202 ValidateCar request.
- 203 Checkout inserts a request log, validates request fields, checks duplicates, parses checkout timestamps, and builds an order candidate before FreeCharge eligibility handling.
- `amount < 0` is invalid input and follows current validation behavior.
- `amount == 0` preserves existing `NoCharge` behavior and does not call Retail.
- Duplicate checkout by `requestId` or `carId + startTime + endTime` returns `EC215`, creates no duplicate order, and does not call Retail.
- For valid, non-duplicate, positive-amount checkout, AutoCharge reads the successful 202 ValidateCar request log before calling Retail.
- If successful 202 `requestTime` or vehicle UUID cannot be used, AutoCharge does not call Retail and creates `EligibilityPending`.
- If 202 eligibility inputs are usable, AutoCharge calls Retail before persisting a positive-amount order as `Unpaid` and before starting payment.
- Retail eligible creates `NoChargePromotion`; Retail not eligible continues existing checkout status logic; Retail failure or invalid-vehicle 4xx creates `EligibilityPending`.
- Pending retry processes the existing `EligibilityPending` order every 5 minutes until 12 attempts or 60 minutes pending age.
- Pending retry eligible updates the existing order to `NoChargePromotion`.
- Pending retry not eligible continues existing checkout status decision when enough data exists.
- Pending retry failures keep `EligibilityPending` and produce warning or manual recovery evidence at the approved thresholds.

## Order State And Idempotency

| Status | Meaning | Payment | Invoice |
|--------|---------|---------|---------|
| `NoCharge` | Existing zero-amount status. | No | No |
| `NoChargePromotion` | Existing status value `12`; selected FreeCharge physical status. | No | No |
| `Unpaid` | Existing payable status. | Yes | Through normal paid flow |
| `Paid` | Existing paid status. | No new payment | Normal paid invoice rules apply |
| `EligibilityPending` | New status for Retail eligibility uncertainty or unusable eligibility inputs. Not unpaid debt, failed payment, outstanding payment, or a later-202 blocker. | No | No |

- Existing duplicate keys remain `requestId` and `carId + startTime + endTime`.
- Duplicate checkout preserves current `EC215`, creates no duplicate order, and does not call Retail.
- Pending retry updates the existing CPO order and shall not insert a replacement order.
- `EligibilityPending` can transition to `NoChargePromotion` when retry finds eligibility.
- `EligibilityPending` can transition through existing checkout status logic when retry finds not eligible and enough data exists.
- `EligibilityPending` remains pending when retry still fails or recovery threshold has not been resolved.
- Payment-capable entry points must only process final status `Unpaid`.
- Invoice-capable entry points must not issue invoices for `NoChargePromotion` or `EligibilityPending`.

## Data Model And Compatibility

- `lxm_cpo_request_logs.api_type` keeps its current meaning: `202` is ValidateCar and `203` is Checkout.
- The order-level decision is stored in current `lxm_cpo_orders.status`, not `order_status`.
- FreeCharge maps to current `LxmCpoOrderStatusNoChargePromotion = 12`.
- `EligibilityPending` is a new order status for Retail query failure, Retail invalid-vehicle 4xx, or unusable successful 202 eligibility inputs.
- The exact numeric enum/database value for `EligibilityPending`, app/admin labels, and compatibility behavior can be finalized during implementation unless TPM requires a specific value before handoff.
- v1 does not create a FreeCharge trace table.
- v1 does not require `eligibility_decision`, `eligibility_reason`, `eligibility_checked_at`, `has_promotion_id`, `campaign_id`, `promotion_id`, `retail_request_id`, `retail_http_status`, `retry_count`, `last_retry_at`, or `resolved_at`.
- Pending age uses existing order timestamps, and retry evidence uses scheduler/job logs linked by `order_id` and `request_id`.
- Consumers that assume a closed order-status set must tolerate existing `NoChargePromotion` as FreeCharge and the new `EligibilityPending`.
- Any consumer that treats positive amount as payable without checking final status can create payment or invoice leakage and must be guarded.

## Error Handling Matrix

| Failure Case | Business State | Feedback | Recovery Path | Owner | Evidence |
|--------------|----------------|----------|---------------|-------|----------|
| Retail timeout during 203 Checkout | Order is `EligibilityPending`; payment and invoice blocked. | Existing 203 success contract to CPO/LXM; pending status recorded. | Retry every 5 minutes until 12 attempts or 60 minutes. | AutoCharge operations | Pending order, order age, scheduler/job logs linked by `order_id` and `request_id`. |
| Retail 5xx, network error, connection refused, temporary unavailable, or parse failure | Order is `EligibilityPending`; payment and invoice blocked. | Existing 203 success contract to CPO/LXM; pending status recorded. | Retry every 5 minutes until 12 attempts or 60 minutes. | AutoCharge operations | Pending order, order age, scheduler/job logs linked by `order_id` and `request_id`. |
| Retail 4xx caused by missing or invalid vehicle UUID | Order is `EligibilityPending`; payment and invoice blocked; not treated as not eligible. | Alert for recovery; existing 203 success contract to CPO/LXM. | Manual investigation or corrected retry path. | AutoCharge operations with TPM/Retail support if needed | Decision record, pending order evidence, Retail response evidence. |
| Missing successful 202 log, missing 202 `requestTime`, unparsable 202 `requestTime`, or unavailable vehicle UUID | Order is `EligibilityPending`; Retail is not called; payment and invoice blocked. | Existing 203 success contract to CPO/LXM; missing-input evidence recorded. | Retry or reconcile later using approved pending policy. | AutoCharge operations | Pending order and missing-input evidence. |
| Duplicate 203 Checkout | Existing order remains authoritative; no duplicate order created. | Current `EC215` response. | Do not repeat Retail call. | AutoCharge service owner | Duplicate key evidence by `requestId` or `carId + startTime + endTime`. |
| Negative 203 Checkout amount | Request invalid; no order should be created. | Current validation error behavior. | No retry; caller must send valid amount. | AutoCharge service owner | Request validation evidence. |
| FreeCharge order enters payment flow | Payment leakage risk. | Alert, stop payment if possible, mark reconciliation required. | Manual reconciliation and guard correction. | AutoCharge operations | Alert and reconciliation record. |
| FreeCharge order enters invoice issuance | Invoice leakage risk. | Alert, stop invoice if possible, mark reconciliation required. | Manual reconciliation and guard correction. | AutoCharge operations with Finance/Tax if needed | Alert and reconciliation record. |
| Pending order enters payment flow | Payment leakage risk before eligibility resolved. | Alert, stop payment if possible, mark reconciliation required. | Manual reconciliation and guard correction. | AutoCharge operations | Alert and reconciliation record. |
| Pending order enters invoice issuance | Invoice leakage risk before eligibility resolved. | Alert, stop invoice if possible, mark reconciliation required. | Manual reconciliation and guard correction. | AutoCharge operations with Finance/Tax if needed | Alert and reconciliation record. |
| Pending order older than 30 minutes | Stuck pending warning. | Operator warning. | Continue retry until 12 attempts or 60 minutes unless manually resolved earlier. | AutoCharge operations | Pending age and retry evidence. |
| Pending order older than 60 minutes or reaches 12 failed retry attempts | Stuck pending requiring manual recovery. | Manual recovery alert. | Manual investigation, corrected retry path, or reconciliation. | AutoCharge operations | Pending age, retry count or job evidence, recovery record. |

## Observability And Recovery

- Detect `NoChargePromotion` as FreeCharge orders that enter payment.
- Detect `NoChargePromotion` as FreeCharge orders that enter invoice issuance.
- Detect `EligibilityPending` orders that enter payment.
- Detect `EligibilityPending` orders that enter invoice issuance.
- Detect `EligibilityPending` orders older than 30 minutes for warning.
- Detect `EligibilityPending` orders older than 60 minutes for manual recovery.
- Detect `EligibilityPending` retries that reach 12 failed attempts.
- Extend existing abnormal order/payment/invoice reports because they do not explicitly detect FreeCharge-or-pending payment/invoice leakage today.
- Update redo jobs and redo result reporting to tolerate the future `EligibilityPending` physical value.
- Manual recovery is owned by AutoCharge operations, with Finance/Tax involved for invoice leakage and TPM/Retail support involved for invalid-vehicle or eligibility API recovery when needed.

## Non-Call And No-Change Constraints

- Do not change existing CPO/LXM 202 ValidateCar or 203 Checkout HTTP contracts.
- Do not change existing non-FreeCharge 202/203 behavior.
- Do not call Retail from 202 ValidateCar in v1.
- Do not call Retail for duplicate 203 Checkout.
- Do not call Retail for `amount == 0`.
- Do not call Retail when successful 202 eligibility inputs are unusable; create `EligibilityPending` instead.
- Do not infer FreeCharge eligibility from order type, vehicle model, amount, DMS data, card status, owner type, 202 result, VIN, `car_no`, or `carId`.
- Do not send VIN, `car_no`, or `carId` as Retail `vehicle_id`.
- Do not use 203 `startTime`, 203 Checkout time, retry time, charging interval overlap, or mid-session activation as v1 eligibility reference.
- Do not retroactively grant FreeCharge if eligibility becomes active after successful 202 ValidateCar `requestTime`.
- Do not add FreeCharge traceability fields or retry metadata storage in v1.
- Do not issue a zero-amount invoice for FreeCharge v1.
- Do not treat `EligibilityPending` as unpaid debt, failed payment, outstanding payment, or any equivalent future-202 blocker.
- Do not alter 203 `data.amount` to represent payment bypass; keep the original checkout amount in the response.

## Source Decisions

- SRC-002: current code uses `lxm_cpo_orders.status`, duplicate checkout returns `EC215`, negative amount is invalid, 202 checks bound-card and card-expiry before charging starts, live card authorization happens later only for `Unpaid`, and payment/invoice guards must cover helper, redo, scheduler, and reporting paths.
- SRC-003: target stage is 2026-06-10; FreeCharge maps to `NoChargePromotion`; `EligibilityPending` is new; FreeCharge skips payment and invoice.
- SRC-004: Retail `charging_time` source is successful 202 ValidateCar `requestTime`; unusable 202 eligibility inputs enter `EligibilityPending`.
- SRC-005: existing 202/203 HTTP contracts must not change; Retail timeout/retry policy, invalid-vehicle 4xx handling, CPO/LXM response mapping, and original `data.amount` behavior are approved for the pre-spec baseline.
- SRC-006: existing `EligibilityPending` FreeCharge orders must not block future 202 ValidateCar requests or be treated as unpaid/outstanding payment.
- SRC-007: mid-session or post-202 eligibility activation is deferred; v1 does not retroactively grant FreeCharge after the successful 202 ValidateCar `requestTime`.
