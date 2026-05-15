# Spec Kit Input Package Index: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Status:** Draft

| Package Slug | Status | Scope Summary | Dependencies | Source Decisions | Handoff Order |
|--------------|--------|---------------|--------------|------------------|---------------|
| autocharge-freecharge | Draft | Additive 203 Checkout FreeCharge eligibility check, current-code status mapping, payment/invoice/redo/reporting guards, pending resolution, and compatibility guards that preserve existing 202/203 HTTP contracts, preserve current 202 card-validation boundaries, prevent `EligibilityPending` from blocking future 202 ValidateCar requests, and defer retroactive mid-session eligibility. | Retail eligibility API, existing AutoCharge 202/203 flow, existing 202 blocker rules, current card validation/payment authorization boundary, current `lxm_cpo_orders.status` enum, payment flow, invoice flow, pending retry/operations policy. | 202 unchanged; 203 is decision point; existing 202/203 HTTP contracts unchanged; existing 202 bound-card/card-expiry checks unchanged; `EligibilityPending` does not block later 202; Retail is source of truth; Retail `charging_time` source is 202 `requestTime` converted to RFC3339 UTC; no retroactive grant after 202 reference time; FreeCharge maps to `NoChargePromotion = 12`; `EligibilityPending` is new; traceability deferred. | 1 |

## Handoff Notes

- This package is draft-only and must not be handed to `speckit-specify` until the product baseline is accepted and PO/TPM handoff approval is recorded.
- Blocking clarifications CL-001, CL-003, and CL-005 are answered by SRC-005.
- SRC-002 codebase alignment must be applied before package acceptance so Spec Kit does not inherit outdated field, enum, duplicate-response, amount, timestamp, or guard assumptions from SRC-001.
- SRC-002 also records the current credit-card validation boundary: 202 validates bound-card availability and card expiry before charging starts, while live ECPay authorization happens later for `Unpaid` orders.
- SRC-003 clarification decisions must be applied before package acceptance so Spec Kit uses the selected 2026-06-10 stage target, `NoChargePromotion` FreeCharge mapping, new `EligibilityPending` status, and no-invoice/no-payment FreeCharge policy.
- SRC-004 clarification decisions must be applied before package acceptance so Spec Kit uses successful 202 ValidateCar `requestTime` as the Retail `charging_time` source and sends unusable 202 eligibility inputs to `EligibilityPending`.
- SRC-005 clarification decisions must be applied before package acceptance so Spec Kit preserves existing 202/203 HTTP contracts, uses the approved timeout/retry policy, applies Retail invalid-vehicle 4xx pending behavior, and returns the existing 203 success response contract for FreeCharge and pending cases.
- SRC-006 clarification decisions must be applied before package acceptance so Spec Kit does not treat `EligibilityPending` as a 202 outstanding-payment blocker.
- SRC-007 clarification decisions must be applied before package acceptance so Spec Kit keeps v1 eligibility fixed to successful 202 ValidateCar `requestTime` and defers mid-session or retroactive eligibility.
