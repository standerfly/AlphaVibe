# Pre-Spec Handoff Checklist: AutoCharge FreeCharge

**Feature Slug:** autocharge-freecharge
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Draft

## Product Baseline

- [x] `docs/spec-intake/index.md` lists this feature workspace
- [ ] `product-spec.md` status is `Accepted`
- [ ] PO and TPM approval are recorded in `product-spec.md`
- [x] All raw source material for this feature is listed in `intake-index.md`
- [x] Blocking questions in `clarification-log.md` are resolved
- [x] In-scope and out-of-scope decisions are recorded in `scope-decision.md`
- [x] `product-spec.md` includes the required supporting-artifact summary
- [x] Relevant failure behavior is defined, or explicitly marked not applicable

## Dynamic Readiness Checks

- [x] `supporting-artifacts/readiness-checks.md` has been generated
- [x] Feature traits and required supporting artifacts are recorded
- [x] Every required supporting artifact is complete and linked from `product-spec.md`
- [x] Every not-applicable artifact has an explicit rationale
- [x] Error-handling matrix or equivalent section is complete when required

## Spec Kit Input Packages

- [x] `spec-kit-inputs/index.md` lists every generated input package
- [x] Each input package has exactly one Spec Kit feature boundary
- [x] Each input package includes concise summaries for required supporting artifacts
- [x] Each input package is self-contained and does not rely on supporting artifacts for required API, workflow, state, data, error, observability, or compatibility behavior
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`
- [x] Each accepted `speckit-input.md` links back to source decisions
- [x] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

- SRC-003 captures the 2026-05-12 clarification answers: target stage timing is 2026-06-10, FreeCharge maps to `NoChargePromotion`, `EligibilityPending` is new, and FreeCharge skips invoice issuance and payment deduction.
- SRC-004 captures the 2026-05-12 clarification answers: Retail `charging_time` source is successful 202 ValidateCar `requestTime`, and unusable 202 eligibility inputs enter `EligibilityPending`.
- SRC-005 captures the 2026-05-12 clarification answers: CL-001, CL-003, and CL-005 are resolved; existing 202/203 HTTP contracts must remain unchanged; FreeCharge is additive and must not impact existing non-FreeCharge behavior.
- SRC-006 captures the 2026-05-12 clarification answer: `EligibilityPending` must not block future 202 ValidateCar requests and must not be treated as unpaid/outstanding payment.
- SRC-007 captures the 2026-05-12 clarification answer: v1 does not retroactively grant FreeCharge for mid-session or post-202 eligibility activation; eligibility is evaluated against successful 202 ValidateCar `requestTime` only.
- SRC-002 captures the current credit-card validation boundary: 202 checks bound-card availability and card expiry before charging starts, while live ECPay authorization happens later only for `Unpaid` orders.
- `spec-kit-inputs/autocharge-freecharge/speckit-input.md` now includes self-contained summaries for API contract, workflow/call ordering, order state/idempotency, data compatibility, error handling, observability/recovery, dependencies, and no-change constraints.
- Product baseline is in review and not yet accepted.
- `spec-kit-inputs/autocharge-freecharge/speckit-input.md` is draft-only until product-spec acceptance and handoff approval are recorded.
