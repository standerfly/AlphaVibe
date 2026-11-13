# Pre-Spec Handoff Checklist: 定錨產業筆記文章自動匯入

**Feature Slug:** investanchors-import
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Blocked

## Product Baseline

- [ ] `docs/spec-intake/index.md` lists this feature workspace
- [ ] `product-spec.md` status is `Accepted`
- [ ] PO and TPM approval are recorded in `product-spec.md`
- [ ] All raw source material for this feature is listed in `intake-index.md`
- [ ] Blocking questions in `clarification-log.md` are resolved
- [ ] In-scope and out-of-scope decisions are recorded in `scope-decision.md`
- [ ] `product-spec.md` includes the required supporting-artifact summary
- [ ] Relevant failure behavior is defined, or explicitly marked not applicable

## Dynamic Readiness Checks

- [ ] `supporting-artifacts/readiness-checks.md` has been generated
- [ ] Feature traits and required supporting artifacts are recorded
- [ ] Every required supporting artifact is complete and linked from `product-spec.md`
- [ ] Every not-applicable artifact has an explicit rationale
- [ ] Error-handling matrix or equivalent section is complete when required

## Spec Kit Input Packages

- [ ] `spec-kit-inputs/index.md` lists every generated input package
- [ ] Each input package has exactly one Spec Kit feature boundary
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`
- [ ] Each accepted `speckit-input.md` links back to source decisions
- [ ] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

- 阻擋項：Q-004（已讀副作用）、Q-005（儲存位置與查詢介面）、Q-008（個人使用條款）、Q-011（兩台裝置上限）；其餘支撐文件為 Draft，待上述定案後轉 Complete。
- `product-spec.md` 標頭的 Function Branch 為 `function/investanchors-import`，但該分支尚未建立；目前產物在 `claude/admiring-ptolemy-1jaw79`（基於 `function/alphavibe`），合併去向待 PO 決定。
