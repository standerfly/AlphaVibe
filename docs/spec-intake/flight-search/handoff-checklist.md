# Pre-Spec Handoff Checklist: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
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

### 交接就緒（2026-09-23）

`product-spec.md` 已取得 PO 接受，PO 並於同日明確回覆「核准拆包」，
兩個輸入包因此標記 `Accepted`，本檢核表轉為 `Ready`。

需求基線歷經三次修訂，全部追溯到 PO 原話：
1. 三個 Blocking 取捨（Q-015 間隔為偏好／Q-016 達標用四段票價／Q-017 每週重掃）
2. 排除月份改為 1–12 自由複選（南北半球旺季相反）＋貨幣統一 NTD
3. 新增第4段延後策略（FR-19~FR-21），與第1段對稱

最終規模：21 條功能需求、12 個驗收情境、6 個成功標準、14 項約束、
8 列錯誤處理矩陣。

交接順序：
1. `flight-scan-page` — 分頁、查詢條件 CRUD、掃描、兩端間隔策略、速率守衛
2. `flight-price-tracking` — 排程重掃、達標通知、資料過期標示

### 非阻斷的已知待辦

- Q-018 價格歷史保留：建議記錄但 MVP 可只存最新值
- Q-019 多目的地支援：設計上不綁死，MVP 僅以布拉格驗證
- Q-020 重掃失敗通知：MVP 僅 UI 標示過期
- CON-02／CON-08：速率上限與促銷艙 validity 上限均為推估值，尚未長期驗證
