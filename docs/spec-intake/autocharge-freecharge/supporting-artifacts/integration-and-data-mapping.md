# Integration And Data Mapping: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Status:** Complete

## Integration Boundary

| System | Responsibility | Source |
|--------|----------------|--------|
| AutoCharge Service | Calls Retail during 203 Checkout, decides CPO order status, controls payment and invoice flow, and preserves existing CPO/LXM 202/203 HTTP contracts. | SRC-001, SRC-005 |
| Retail | Owns FreeCharge eligibility creation and the AutoCharge-facing eligibility API. | SRC-001 |
| Payment Flow | Charges only final `Unpaid` orders. | SRC-001 |
| Invoice Flow | Issues invoices only through the normal paid flow; FreeCharge and pending orders do not issue invoices in v1. | SRC-001, SRC-003 |
| Operations or Scheduler | Retries orders with `EligibilityPending` and alerts on leakage or stuck pending records. | SRC-001, SRC-002, SRC-003 |

## Data Mapping

| Retail Field | AutoCharge Source | Product Rule | Source |
|--------------|-------------------|--------------|--------|
| `vehicle_id` | Vehicle UUID from the successful 202 ValidateCar request log, or equivalent successful 202 eligibility input | Required. Must be vehicle UUID, not VIN, `car_no`, or `carId`. If unavailable, do not call Retail and create `EligibilityPending`. | SRC-001, SRC-002, SRC-004 |
| `charging_time` | Successful 202 ValidateCar request log `requestTime` | Required. 202 `requestTime` is the eligibility reference time and is sent to Retail as RFC3339 UTC. 203 `startTime` remains the order charging start time and duplicate-check input. Existing CPO/LXM timestamp fields remain epoch-millisecond strings. | SRC-001, SRC-002, SRC-004, SRC-005 |

## Checkout Integration Rules

- AutoCharge shall call Retail only after checkout payload validation, duplicate checks, checkout parsing, order candidate creation, successful 202 eligibility input lookup, vehicle UUID resolution, and 202 `requestTime` availability. [SRC-001, SRC-004]
- AutoCharge shall call Retail before persisting a positive-amount order as `Unpaid` and before starting payment. [SRC-001]
- AutoCharge does not need to call Retail for `amount == 0` orders. Negative amount is invalid input under the current 203 Checkout DTO validation. [SRC-001, SRC-002]
- Duplicate checkout currently returns `EC215`; preserving that behavior means Retail eligibility must not be called for duplicate requests. [SRC-002]
- If AutoCharge cannot use the successful 202 ValidateCar eligibility inputs, including 202 `requestTime` or vehicle UUID, AutoCharge shall not call Retail, shall not mark the order as FreeCharge, and shall create `EligibilityPending`. [SRC-004]
- Existing CPO/LXM 202/203 HTTP contracts must not change. FreeCharge and `EligibilityPending` 203 responses keep HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`. [SRC-005]

## Current Code Alignment Constraints

- The current order status field is `lxm_cpo_orders.status`, not `order_status`. [SRC-002]
- Existing `NoChargePromotion = 12` is the selected FreeCharge final state. Add a new `EligibilityPending` status for Retail query failures. [SRC-002, SRC-003]
- Existing payment and invoice helpers assume caller-side eligibility; FreeCharge implementation must add guards in 203 Checkout, redo flows, `authPaymentForOrder`, and `issueInvoiceForPayment`. [SRC-002]

## Timeout, Retry, And Failure Semantics

| Scenario | Product Behavior | Status |
|----------|------------------|--------|
| Retail eligible | Persist `NoChargePromotion`; skip payment and invoice issuance. | Complete |
| Retail not eligible | Continue existing checkout status logic; payment only for final `Unpaid`. | Complete |
| Retail query failure | Persist new `EligibilityPending`; block payment and invoice; retry later. | Complete; timeout and retry policy defined by SRC-005 |
| Retail invalid-vehicle 4xx | Persist new `EligibilityPending`; block payment and invoice; alert for recovery; do not continue to payment. | Complete |
| Pending retry eligible | Update existing order to `NoChargePromotion`; keep payment skipped and invoice skipped. | Complete |
| Pending retry not eligible | Continue existing checkout status decision using existing data when enough data exists. | Complete |
| Pending retry fails repeatedly | Keep `EligibilityPending`; warn after 30 minutes and require manual recovery after 60 minutes or 12 failed attempts. | Complete |

## Integration Decisions

- Retail timeout is 3 seconds with no inline retry during synchronous 203 Checkout. [SRC-005]
- Pending retry runs every 5 minutes and stops after 12 attempts or 60 minutes pending age. [SRC-005]
- Pending warn threshold is 30 minutes; manual recovery threshold is 60 minutes or 12 failed attempts. [SRC-005]
- v1 does not add a FreeCharge trace table; retry evidence uses existing order timestamps and scheduler/job logs linked by `order_id` and `request_id`. [SRC-005]
- Retail `charging_time` wire format is RFC3339 UTC derived from successful 202 `requestTime`. [SRC-005]
- Existing 202/203 HTTP contracts must remain unchanged. [SRC-005]
