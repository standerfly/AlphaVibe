# Pre-Spec Handoff Checklist: 機票查詢分頁（外站四段票掃描＋價格追蹤）

**Feature Slug:** flight-search
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Draft

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
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`
- [x] Each accepted `speckit-input.md` links back to source decisions
- [x] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

### 目前唯一的阻擋項：交接核准

`product-spec.md` 已於 2026-09-23 取得 PO 接受（接受證據見該文件表頭）。
PO 審閱時提出兩項指正，均已修正並反映到需求與程式：

1. 「避開夏季」改為 **1–12 月自由複選的排除月份**——南半球目的地旺季與
   北半球相反，寫死季節會讓南半球航線判斷錯誤（FR-06、CON-12）
2. **貨幣統一 NTD**；對外查價服務仍須送 ISO 4217 代碼 `TWD`
   （`NTD` 不被接受），兩者為同一貨幣的不同寫法（CON-13）

兩個 `speckit-input.md` 仍為 `Draft`，因為依 ADR-0027 與 prespec skill
的硬邊界，輸入包標記 `Accepted` 需要**明確記錄的 PO/TPM 交接核准**。
PO 的「其他OK」是對 product-spec 內容的接受，是否同時涵蓋「拆成
flight-scan-page ＋ flight-price-tracking 兩個包」的核准並不明確，
故保守維持 Draft，不代 PO 認定。

取得交接核准後本檢核表即可轉為 `Ready`，以 `speckit-specify` 接手
handoff order 1（flight-scan-page）。

### 非阻斷的已知待辦

- Q-018 價格歷史保留：建議記錄但 MVP 可只存最新值
- Q-019 多目的地支援：設計上不綁死，MVP 僅以布拉格驗證
- Q-020 重掃失敗通知：MVP 僅 UI 標示過期
- CON-02／CON-08：速率上限與促銷艙 validity 上限均為推估值，尚未長期驗證
