# Pre-Spec Handoff Checklist: Us Stocks

**Feature Slug:** us-stocks
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Draft

## Product Baseline

- [x] `docs/spec-intake/index.md` lists this feature workspace
- [x] `product-spec.md` status is `Accepted`（2026-09-04，PO Stander 驗收）
- [x] PO and TPM approval are recorded in `product-spec.md`
- [x] All raw source material for this feature is listed in `intake-index.md`
- [x] Blocking questions in `clarification-log.md` are resolved（Q-001~Q-004 已於2026-09-04回答）
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
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`（目前 Draft，待 handoff核准）
- [ ] Each accepted `speckit-input.md` links back to source decisions（內容已具備，待正式Accepted後此項才算生效）
- [ ] Handoff order is recorded for accepted input packages（Order已記錄為1，但套件尚未Accepted，此checkbox語意上待正式核准後才勾選）

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

- 2026-09-04（第一輪）：guided full flow 首輪完成，產出完整草稿，但
  Q-001~Q-004 未回答，product-spec.md 維持 `Draft`。
- 2026-09-04（第二輪）：Stander 回答 Q-001~Q-004。`product-spec.md` 狀態
  推進為 `In Review`。
- 2026-09-04（第三輪）：Stander 要求就 Q-001 補充查證 FMP/Polygon.io/
  Alpha Vantage 三個免費美股資料API，查證後修正 Q-001 決定為「免費API
  多來源（FMP主要+備援）」，已連動更新 product-spec.md 新增 §Integration
  Note 等多處。
- 2026-09-04（第四輪）：Stander 對「還有其他要補充或修正的地方嗎？還是
  可以驗收了？」明確回覆「可以驗收了」——構成 ADR-0027 要求的顯式 PO/TPM
  驗收證據。`product-spec.md` 狀態改為 `Accepted`，驗收證據已記錄在
  product-spec.md 檔頭。已產出單一 Spec Kit input package
  `spec-kit-inputs/us-stocks/speckit-input.md`（Status: Draft，不拆分，
  理由見 scope-decision.md §Split Feature Decisions）。
  `prespec_validate.py us-stocks` 機械檢查通過。
- **下一步（待使用者明確表態，AI 不自行認定）**：Handoff Approval 三項
  checkbox 均未打勾——需要 PO 確認「product spec 到 Spec Kit input 的
  拆分方式可接受」、TPM 確認「input package 已可交給 speckit-specify」。
  確認後才能把 speckit-input.md 狀態改為 `Accepted`、本檔案狀態改為
  `Ready`，之後才能執行 `speckit-specify`（非本 skill 職責範圍）。
