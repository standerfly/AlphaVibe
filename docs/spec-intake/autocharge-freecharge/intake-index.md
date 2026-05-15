# Intake Index: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Last Updated:** 2026-05-12

## Source Inventory

| Source ID | File Or Reference | Source Type | Source Date | Stakeholder Or Owner | Processing Status | Notes |
|-----------|-------------------|-------------|-------------|----------------------|-------------------|-------|
| SRC-001 | raw/autocharge_freecharge_spec.md | Existing product and implementation specification draft | Unknown; indexed 2026-05-11 | joe-yf-lin from registry; source author not stated | Extracted | Interpretable source. Contains scope, terminology, existing 202/203 context, target checkout flow, Retail API contract, status behavior, data scope, idempotency, pending resolution, payment/invoice controls, acceptance criteria, and open issues. |
| SRC-002 | raw/src-002-autocharge-freecharge-codebase-alignment.md | Codebase reality check and alignment addendum | 2026-05-12 | Codex codebase inspection; requires PO/TPM review | Extracted | Corrects current-code assumptions in SRC-001: status field is `lxm_cpo_orders.status`, current enum includes `NoChargePromotion` but not `FreeCharge`/`EligibilityPending`, duplicate checkout returns `EC215`, 203 timestamps are epoch milliseconds, negative amount is invalid, and payment/invoice guards must cover redo/helper/reporting paths. |
| SRC-003 | raw/src-003-clarification-answers-2026-05-12.md | PO/TPM clarification answer from chat | 2026-05-12 | User-provided clarification; requires PO/TPM acceptance evidence before final baseline | Extracted | Provides target stage timing, maps FreeCharge to existing `NoChargePromotion`, requires new `EligibilityPending` status, confirms FreeCharge skips invoice and payment deduction, and leaves retry/API details for discussion. |
| SRC-004 | raw/src-004-clarification-answers-2026-05-12-charging-time.md | PO/TPM clarification answer from chat | 2026-05-12 | User-provided clarification; requires PO/TPM acceptance evidence before final baseline | Extracted | Confirms Retail `charging_time` source is the successful 202 ValidateCar request log `requestTime`, not 203 `startTime`, and unusable 202 eligibility inputs enter `EligibilityPending`. |
| SRC-005 | raw/src-005-clarification-answers-2026-05-12-contract-and-retry.md | PO/TPM clarification answer from chat | 2026-05-12 | User-provided clarification; requires final product-spec acceptance evidence before baseline acceptance | Extracted | Accepts the recommended CL-001, CL-003, and CL-005 decisions; defines P0 priority, retry and timeout policy, Retail wire format, Retail 4xx behavior, CPO/LXM response mapping, and the hard constraint that existing 202/203 HTTP contracts must not change. |
| SRC-006 | raw/src-006-clarification-answers-2026-05-12-eligibility-pending-202.md | PO/TPM clarification answer from chat | 2026-05-12 | User-provided clarification; requires final product-spec acceptance evidence before baseline acceptance | Extracted | Confirms a prior `EligibilityPending` FreeCharge order must not block future 202 ValidateCar requests, must not be treated as unpaid/outstanding debt, and must remain an operations/retry concern rather than customer charging denial. |
| SRC-007 | raw/src-007-clarification-answers-2026-05-12-mid-session-eligibility.md | PO/TPM clarification answer from chat | 2026-05-12 | User-provided clarification; requires final product-spec acceptance evidence before baseline acceptance | Extracted | Records the deferred boundary that v1 evaluates eligibility only against successful 202 ValidateCar `requestTime` and does not retroactively grant FreeCharge for mid-session or post-202 eligibility activation. |

## Processing Notes

- `.gitkeep` is present only to preserve the raw directory and is not treated as product source material.
- SRC-001 is detailed enough to draft a product baseline and supporting readiness artifacts.
- SRC-001 also contains unresolved decisions that block PO/TPM acceptance and Spec Kit handoff.
- SRC-002 must be applied before handoff so the accepted product baseline matches the current FVS-VAS codebase rather than only the proposed design in SRC-001.
- SRC-003 resolves the FreeCharge status mapping and invoice/payment policy, partially answers target timing, and confirms CL-003 and CL-005 still need discussion.
- SRC-004 partially resolved CL-005 for `charging_time` source and unavailable 202 eligibility input behavior.
- SRC-005 resolves the remaining blocking clarification decisions and adds the explicit compatibility constraint that FreeCharge is additive to AutoCharge and must not change the existing CPO/LXM 202/203 HTTP contract.
- SRC-006 clarifies that stuck or unresolved `EligibilityPending` orders must not be added to 202 ValidateCar blocker logic.
- SRC-007 records the mid-session eligibility activation boundary as deferred future scope.
