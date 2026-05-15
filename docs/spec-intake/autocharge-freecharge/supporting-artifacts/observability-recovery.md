# Observability And Recovery: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12
**Status:** Complete

## Observability Requirements

- Detect `FreeCharge` orders that enter payment. [SRC-001]
- Detect `FreeCharge` orders that enter invoice issuance. [SRC-001, SRC-003]
- Detect `EligibilityPending` orders that enter payment. [SRC-001]
- Detect `EligibilityPending` orders that enter invoice issuance. [SRC-001, SRC-003]
- Detect `EligibilityPending` orders older than 30 minutes for warning and older than 60 minutes for manual recovery. [SRC-005]
- Detect `EligibilityPending` retries that reach 12 failed attempts. [SRC-005]
- Existing abnormal order/payment/invoice reports do not explicitly detect FreeCharge-or-pending payment/invoice leakage today. They must be extended for `NoChargePromotion` as FreeCharge and new `EligibilityPending`. [SRC-002, SRC-003]
- Existing redo jobs already exclude `NoCharge` and `NoChargePromotion`, but do not know the future pending physical value. They must be updated for new `EligibilityPending`. [SRC-002, SRC-003]

## Manual Recovery Expectations

| Condition | Recovery Expectation | Owner | Status |
|-----------|----------------------|-------|--------|
| FreeCharge payment leakage | Stop payment if possible, mark reconciliation required, and investigate payment guard failure. | AutoCharge operations | Complete |
| FreeCharge invoice leakage | Stop invoice if possible, mark reconciliation required, and investigate invoice guard failure. | AutoCharge operations with Finance/Tax if needed | Complete |
| EligibilityPending payment leakage | Stop payment if possible, mark reconciliation required, and investigate payment guard failure. | AutoCharge operations | Complete |
| EligibilityPending invoice leakage | Stop invoice if possible, mark reconciliation required, and investigate invoice guard failure. | AutoCharge operations with Finance/Tax if needed | Complete |
| Stuck EligibilityPending warning | Alert after 30 minutes pending age. | AutoCharge operations | Complete |
| Stuck EligibilityPending manual recovery | Manual recovery after 60 minutes pending age or 12 failed retry attempts. | AutoCharge operations | Complete |

## Reconciliation Scope

Included in v1: [SRC-001]

- FreeCharge order entered payment.
- FreeCharge order entered invoice issuance.
- EligibilityPending order entered payment.
- EligibilityPending order entered invoice issuance.
- EligibilityPending older than 30 minutes.
- EligibilityPending older than 60 minutes.
- EligibilityPending retry reached 12 failed attempts.
- Report coverage for the approved FreeCharge and pending physical statuses in abnormal reports, duplicate payment/invoice reports, and redo result emails. [SRC-002]

Excluded from v1 because traceability storage is deferred: [SRC-001]

- FreeCharge order missing `has_promotion_id`.
- FreeCharge order missing `campaign_id` or `promotion_id`.
- FreeCharge order has positive amount but no trace.
- FreeCharge order missing `eligibility_decision`.

## Operational Decisions

- Retail timeout is 3 seconds in synchronous 203 Checkout with no inline retry. [SRC-005]
- Pending retry runs every 5 minutes and stops after 12 attempts or 60 minutes pending age, whichever comes first. [SRC-005]
- Warning starts after 30 minutes pending age. Manual recovery starts after 60 minutes or 12 failed retry attempts. [SRC-005]
- v1 does not add a FreeCharge trace table. Pending age uses existing order timestamps, and retry evidence uses scheduler/job logs linked by `order_id` and `request_id`. [SRC-005]
- Existing CPO/LXM 202/203 HTTP contracts must remain unchanged. [SRC-005]
