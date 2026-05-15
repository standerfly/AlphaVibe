# AutoCharge FreeCharge Mid-Session Eligibility Boundary

**Source ID:** SRC-007
**Source Date:** 2026-05-12
**Source Type:** PO/TPM clarification answer from chat
**Feature Slug:** autocharge-freecharge

## Answers Provided

1. If a vehicle becomes FreeCharge-eligible after the successful 202 ValidateCar `requestTime` but before or during the charging session, v1 does not retroactively grant FreeCharge.
2. FreeCharge eligibility is evaluated against the successful 202 ValidateCar `requestTime` only.
3. v1 does not evaluate charging-interval overlap, mid-session eligibility activation, 203 Checkout time, or campaign qualification changes that occur after the successful 202 ValidateCar `requestTime`.
4. This boundary case shall be recorded as deferred future scope unless PO/TPM reopens the product decision.

## Interpretation Notes

- This boundary case is not `EligibilityPending` because Retail is not necessarily unavailable and eligibility is not unknown under the v1 rule.
- Implementations must not replace the approved Retail `charging_time` reference with 203 `startTime`, 203 Checkout time, charging interval overlap, or retry-time eligibility unless a future scope decision changes the rule.
