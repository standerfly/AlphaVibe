# Pre-Spec Handoff Checklist: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
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
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`
- [ ] Each accepted `speckit-input.md` links back to source decisions
- [x] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

### 目前卡在哪（2026-09-24）

**唯一的阻斷點是 PO 對 `product-spec.md` 的正式接受**——所有內容面的
工作（釐清問題 Q-001～Q-010 全數 Answered、scope-decision 已定案、
兩份支援文件已完成、兩個 Draft Spec Kit input 包已拆好）都已完成，
不是缺內容，是缺 PO 明確的「接受」動作。

本次 pre-spec 的特殊之處：涉及對**已上線生產功能與資料**（四段票
`trip_days` schema、id=9 既有追蹤條件）的破壞性異動，接受前建議 PO
特別留意 `supporting-artifacts/data-model-migration.md` 與
`product-spec.md` 的「Constraints And Assumptions」章節中標記為
**Assumption** 的兩項（組合數上限 60、id=9 遷移區間 10～14 天）——
這兩個數字是 Claude 提案並經 PO 口頭採納，未逐字精確確認，PO 接受
時可一併確認或修正。

### 下一步

1. PO 檢視 `product-spec.md`，若同意則明確表示接受（例如「我接受這份
   product-spec」），Claude 據此把 Status 改為 `Accepted` 並填入
   `Accepted At`／`Acceptance Evidence`
2. PO 同時確認是否同意兩包（`trip-day-range` → `roundtrip-search`）
   的拆分與交接順序
3. 接受後，兩個 `speckit-input.md` 才能標記 `Accepted`，本檢核表才能
   轉為 `Ready`，進入 `speckit-specify` 階段
