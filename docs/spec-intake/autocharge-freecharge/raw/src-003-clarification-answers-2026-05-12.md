# AutoCharge FreeCharge Clarification Answers

**Source ID:** SRC-003
**Source Date:** 2026-05-12
**Source Type:** PO/TPM clarification answer from chat
**Feature Slug:** autocharge-freecharge

## Answers Provided

1. Target stage timing: the feature is planned to go to stage on 2026-06-10.
2. Status mapping: `NoChargePromotion` represents the FreeCharge state. `EligibilityPending` needs to be added as a new status.
3. Retail timeout and retry policy still needs discussion.
4. FreeCharge orders shall not trigger invoice issuance or payment deduction.
5. Remaining API contract details still need discussion.

## Interpretation Notes

- The target date is interpreted as June 10, 2026 because the answer was provided on 2026-05-12.
- `NoChargePromotion = FreeCharge` means existing `LxmCpoOrderStatusNoChargePromotion = 12` is the selected physical status for FreeCharge unless PO/TPM later changes this decision.
- `EligibilityPending` is an additive order status requirement. The exact numeric enum/database value is an implementation detail unless TPM requires a specific value.
- The invoice decision means FreeCharge v1 skips invoice entirely and does not use a separate zero-amount invoice mode.
