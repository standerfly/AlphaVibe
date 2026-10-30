# Pre-Spec Handoff Checklist: 券商對帳單 Email 自動匯入

**Feature Slug:** broker-statement-import
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Blocked

## Product Baseline

- [x] `docs/spec-intake/index.md` lists this feature workspace
- [ ] `product-spec.md` status is `Accepted`
- [ ] PO and TPM approval are recorded in `product-spec.md`
- [x] All raw source material for this feature is listed in `intake-index.md`
- [ ] Blocking questions in `clarification-log.md` are resolved
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

- 2026-10-31：code review 後補 FR-013（依日期順序）、FR-014（重跑）、FR-009 擴及寫入失敗、通知規則統一；查證資料庫發現既有重複成交（SRC-004）。新增 Q-013、Q-014 待 PO 決定。Q-002 平均成本規則 PO 已於 2026-10-31 確認。
