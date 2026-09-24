# Pre-Spec Handoff Checklist: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
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

### 交接就緒（2026-09-24）

`product-spec.md` 於 2026-09-24 取得 PO 接受（對話中明確回覆「好」），
包含兩項標記為 Assumption 的預設值（id=9 遷移區間 10～14 天、組合數
上限 60／條件）一併採納。兩個 Spec Kit input 包同步轉為 `Accepted`。

交接順序：
1. `trip-day-range`——四段票 `trip_days` 從單一整數升級為區間，含
   id=9 遷移（前提工作，對已上線生產功能與資料的異動）
2. `roundtrip-search`——新增「單純來回」查詢類型（依賴第一包）

### 非阻斷的已知待辦

- 組合數上限（60）與 id=9 遷移區間（10～14 天）為 Claude assumption，
  Spec Kit 技術規劃階段若發現不合理可回頭調整，不需重跑 pre-spec
- 排程／通知／過期防護機制在天數區間化與多目的地情境下是否需要調整
  判定邏輯，留給 Spec Kit `plan.md` 階段逐一驗證（product-spec.md
  「Constraints And Assumptions」已標註此為待驗證的技術假設）
