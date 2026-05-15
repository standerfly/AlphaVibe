# AutoCharge FreeCharge Charging Time Clarification

**Source ID:** SRC-004
**Source Date:** 2026-05-12
**Source Type:** PO/TPM clarification answer from chat
**Feature Slug:** autocharge-freecharge

## Answers Provided

1. Retail `charging_time` shall use the 202 ValidateCar request log `requestTime`.
2. If AutoCharge cannot use the successful 202 ValidateCar request log for the Retail eligibility decision, the order shall enter `EligibilityPending`.

## Interpretation Notes

- 203 `startTime` remains the order charging start time and duplicate-check input, but is not the FreeCharge eligibility reference time.
- AutoCharge should parse the 202 `requestTime` from the existing epoch-millisecond string format and send Retail a confirmed API format after CL-005 is fully closed.
- Missing successful 202 log, missing 202 `requestTime`, or unparsable 202 `requestTime` are treated as eligibility unknown and shall not enter payment or invoice issuance.
