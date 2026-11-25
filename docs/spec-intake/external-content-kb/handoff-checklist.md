# Pre-Spec Handoff Checklist: 外部內容知識庫（YouTube／Podcast／文章）

**Feature Slug:** external-content-kb
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Ready

## Product Baseline

- [x] `docs/spec-intake/index.md` lists this feature workspace
- [x] `product-spec.md` status is `Accepted`
- [x] PO and TPM approval are recorded in `product-spec.md`
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
- [x] Each accepted `speckit-input.md` has `Status: Accepted`
- [x] Each accepted `speckit-input.md` links back to source decisions
- [x] Handoff order is recorded for accepted input packages

## Handoff Approval

- [x] TPM confirms accepted input packages are ready for `speckit-specify`
- [x] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [x] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

- 2026-11-25 PO Accept 需求基線（product-spec.md）。
- API 設計說明依 PO 同意延後至 Spec Kit plan（readiness-checks 已標）。
- 2026-11-25 PO（兼 TPM）核准 speckit-input（external-content-kb，Handoff Order 1）交給 speckit-specify。
