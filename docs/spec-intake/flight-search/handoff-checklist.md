# Pre-Spec Handoff Checklist: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
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
- [x] Each accepted `speckit-input.md` links back to source decisions
- [x] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

### 目前唯一的阻擋項：PO/TPM 接受

`product-spec.md` 內容已完整（18 條功能需求、10 個驗收情境、6 個成功標準、
11 項約束、8 列錯誤處理矩陣），三個 Blocking 問題已由 PO 決定並記錄於
`clarification-log.md`（Q-015／Q-016／Q-017，2026-09-23），
`prespec_validate.py` 回報 mechanically valid。

依 ADR-0027 與 prespec skill 的硬邊界，**不得在沒有 PO/TPM 明確接受證據
的情況下把 `product-spec.md` 標為 `Accepted`**，兩個 `speckit-input.md`
也因此維持 `Draft`。

需要 PO/TPM 提供：
1. 對 `product-spec.md` 的接受確認（將填入 `Accepted At` 與
   `Acceptance Evidence` 欄位）
2. 對「拆成 flight-scan-page ＋ flight-price-tracking 兩個 Spec Kit
   輸入包」的核准

取得上述兩項後，本檢核表可轉為 `Ready`，並以
`speckit-specify` 接手 handoff order 1（flight-scan-page）。

### 非阻斷的已知待辦

- Q-018 價格歷史保留：建議記錄但 MVP 可只存最新值
- Q-019 多目的地支援：設計上不綁死，MVP 僅以布拉格驗證
- Q-020 重掃失敗通知：MVP 僅 UI 標示過期
- CON-02／CON-08：速率上限與促銷艙 validity 上限均為推估值，尚未長期驗證
