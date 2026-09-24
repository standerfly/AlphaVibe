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

### 進度更新（2026-09-24）

**`trip-day-range` 包（Spec Kit `specs/007-trip-day-range/`）已完成並
正式上線（2026-09-24）**：`trip_days` 已改為 `trip_days_min`／
`trip_days_max` 區間、組合數上限守衛（60／條件）已實作並經 264 個
單元測試＋smoke test 119 項驗證；排程／通知／過期防護機制沿用既有
判定邏輯，未發現需要調整（原本標註的待驗證技術假設已驗證成立）。
id=9 已在正式庫遷移至 10～14 天並重新查價（最低價 NT$46,872，14 天，
證實區間確實找到比原固定 12 天更划算的組合），已合併進
`function/alphavibe`、正式服務已重啟套用（T028 完成）。

`roundtrip-search` 包（第二包）可以開始 Spec Kit（`speckit-specify`），
不需要等 `trip-day-range` 先合併／部署到正式環境——兩包在程式碼層級
的依賴（共用天數區間概念與組合數守衛函式）已經在同一個分支上滿足，
但正式環境的合併／部署順序仍建議先 `trip-day-range` 再
`roundtrip-search`，避免正式環境同時處理兩個對已上線功能的異動。

### 非阻斷的已知待辦

- 組合數上限（60）與 id=9 遷移區間（10～14 天）為 Claude assumption，
  執行 T028（正式環境部署）前可視情況再調整，不需重跑 pre-spec
