# Data Model Note: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Status:** Complete

## Data Model Requirements

- The feature shall preserve the meaning of `lxm_cpo_request_logs.api_type`: `202` remains ValidateCar and `203` remains Checkout. [SRC-001]
- The feature shall store the final order-level decision in the current `lxm_cpo_orders.status` field. [SRC-001, SRC-002]
- The current version maps FreeCharge to the existing `LxmCpoOrderStatusNoChargePromotion = 12` status. [SRC-002, SRC-003]
- The current version requires adding a new `EligibilityPending` order status for Retail eligibility query failures. [SRC-001, SRC-002, SRC-003]
- The exact numeric enum/database value for `EligibilityPending`, app/admin labels, and compatibility behavior can be finalized during implementation unless TPM requires a specific value before Spec Kit handoff. [SRC-003]
- The existing CPO/LXM 202 ValidateCar and 203 Checkout HTTP contracts must not change; FreeCharge is represented through internal order status and guards, not through response-schema changes. [SRC-005]

## Explicitly Excluded Data In Current Version

The current version shall not create a dedicated FreeCharge trace table. [SRC-001]

The following fields are not required in v1: [SRC-001]

- `eligibility_decision`
- `eligibility_reason`
- `eligibility_checked_at`
- `has_promotion_id`
- `campaign_id`
- `promotion_id`
- `retail_request_id`
- `retail_http_status`
- `retry_count`
- `last_retry_at`
- `resolved_at`

## Pending Resolution Data Needs

Because v1 does not include dedicated retry metadata fields, the pending-resolution worker must read vehicle and charging information from the existing order or related request log. Retail `charging_time` uses the successful 202 ValidateCar request log `requestTime` converted to RFC3339 UTC for the Retail side-call; current CPO/LXM request logs keep raw epoch-millisecond string timestamps, while 203 `start_time` on `lxm_cpo_orders` remains the order charging start time and duplicate-check input. Retry evidence uses scheduler/job logs linked by `order_id` and `request_id`, and pending age uses existing order timestamps. [SRC-001, SRC-002, SRC-004, SRC-005]

## Compatibility Risks

- Consumers that assume a closed set of order statuses must tolerate the existing `NoChargePromotion` FreeCharge mapping and the new `EligibilityPending` status.
- Existing `NoChargePromotion` behavior, app-facing promotion copy, redo exclusions, and status-list APIs must be reviewed because FreeCharge now reuses that status.
- Any payment or invoice query that treats positive amount as payable without checking final status can create payment or invoice leakage.
- Any analytics or reconciliation process that interprets `api_type = 202` or `api_type = 203` as order status must be corrected.
- Any implementation that changes the existing 202/203 HTTP response body, response code meanings, or timestamp semantics would violate the product constraint. [SRC-005]
