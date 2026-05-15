# Retail API Contract: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Status:** Complete

## Endpoint

```http
GET /promotion/api/v1/freecharge/eligibility
```

Retail is the source of truth for FreeCharge eligibility. AutoCharge shall not infer eligibility from order type, vehicle model, amount, DMS f16, card status, owner type, 202 success or failure, VIN, or `car_no`. [SRC-001]

## Query Parameters

| Parameter | Required | AutoCharge Source | Rules | Source |
|-----------|----------|-------------------|-------|--------|
| `vehicle_id` | Yes | Vehicle UUID from the successful 202 ValidateCar request log, or equivalent successful 202 eligibility input | Must be the vehicle UUID. Must not be VIN, `car_no`, or `carId`. If AutoCharge cannot derive a usable vehicle UUID for Retail, the order enters `EligibilityPending`. | SRC-001, SRC-002, SRC-004 |
| `charging_time` | Yes | Successful 202 ValidateCar request log `requestTime` | 202 `requestTime` is parsed from the existing CPO/LXM epoch-millisecond string and sent to Retail as RFC3339 UTC. 203 `startTime`, 203 Checkout time, retry time, charging-interval overlap, and mid-session eligibility activation are not v1 eligibility references. Retail evaluates `my_start_time <= charging_time < my_end_time`. | SRC-001, SRC-002, SRC-004, SRC-005, SRC-007 |

## Eligible Response

```json
{
  "eligible": true,
  "vehicle_id": "98408b0e-e235-41ff-9698-729138a39d39",
  "my_start_time": "2026-05-27T16:00:00Z",
  "my_end_time": "2026-05-27T16:00:50Z",
  "eligibility_source": "AUTO_DMS_SALES_ORDER",
  "reason": null
}
```

Expected AutoCharge behavior: create the CPO order with `NoChargePromotion` in `lxm_cpo_orders.status`, skip payment, skip invoice issuance, and do not persist campaign traceability fields in v1. [SRC-001, SRC-002, SRC-003]

## Not Eligible Response

```json
{
  "eligible": false,
  "vehicle_id": "98408b0e-e235-41ff-9698-729138a39d39",
  "reason": "NO_ACTIVE_FREECHARGE_PROMOTION"
}
```

Expected AutoCharge behavior: continue existing 203 checkout status logic. Payment may start only if the final status is `Unpaid`. [SRC-001]

## Failure Responses Or Transport Failures

| Case | Expected Product Behavior | Source |
|------|---------------------------|--------|
| Timeout | Create new `EligibilityPending`, block payment and invoice, retry later. | SRC-001, SRC-002, SRC-003 |
| Network error or connection refused | Create new `EligibilityPending`, block payment and invoice, retry later. | SRC-001, SRC-002, SRC-003 |
| Retail 5xx or temporary unavailability | Create new `EligibilityPending`, block payment and invoice, retry later. | SRC-001, SRC-002, SRC-003 |
| Response parse failure | Create new `EligibilityPending`, block payment and invoice, retry later. | SRC-001, SRC-002, SRC-003 |
| Missing successful 202 ValidateCar log, missing 202 `requestTime`, unparsable 202 `requestTime`, or unavailable vehicle UUID from 202 eligibility inputs | Create new `EligibilityPending`, block payment and invoice, retry or reconcile later. | SRC-004 |
| Retail 4xx caused by missing or invalid `vehicle_id` | Create new `EligibilityPending`, block payment and invoice, alert for recovery, and do not treat as not eligible or continue to payment. | SRC-005 |

## CPO/LXM Contract Compatibility Decisions

- The Retail eligibility API is a new AutoCharge side-call and is not part of the CPO/LXM 202/203 HTTP contract. [SRC-005]
- Existing CPO/LXM 202 ValidateCar and 203 Checkout paths, required fields, timestamp field semantics, HTTP status behavior, response code meanings, response body shape, and duplicate behavior must remain compatible. [SRC-005]
- FreeCharge and `EligibilityPending` 203 Checkout responses preserve the existing success contract: HTTP 200, code `00`, message `success`, existing response schema, and original `data.amount`. [SRC-005]
- Duplicate 203 Checkout preserves `EC215`. [SRC-002, SRC-005]
- Retail timeout is 3 seconds in synchronous 203 Checkout with no inline retry. [SRC-005]
- v1 does not retroactively grant FreeCharge when eligibility becomes active after the successful 202 ValidateCar `requestTime`; charging-interval overlap and retroactive campaign adjustment are deferred. [SRC-007]
