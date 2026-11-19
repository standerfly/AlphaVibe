# Pre-Spec Handoff Checklist: Substack 文章自動匯入（011）

**Feature Slug:** substack-import
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Draft

## Product Baseline

- [x] `docs/spec-intake/index.md` lists this feature workspace
- [ ] `product-spec.md` status is `Accepted`
- [ ] PO and TPM approval are recorded in `product-spec.md`
- [x] All raw source material for this feature is listed in `intake-index.md`
- [x] Blocking questions in `clarification-log.md` are resolved（2026-11-19：Q-102／Q-107／Q-115 已答，阻擋清單清零）
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
- [N/A] Each accepted `speckit-input.md` has `Status: Accepted`（目前無 Accepted 套件，兩包皆 Draft）
- [N/A] Each accepted `speckit-input.md` links back to source decisions（同上；Draft 包已有 Source Decisions 節）
- [N/A] Handoff order is recorded for accepted input packages（同上；Draft 包的順序已記於 spec-kit-inputs/index.md）

## Handoff Approval

- [N/A] TPM confirms accepted input packages are ready for `speckit-specify`（無 Accepted 套件，待 PO 審閱後才適用）
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable（未簽核，非 N/A）
- [N/A] No accepted input contains unresolved contradictions or meeting-note noise（無 Accepted 套件）

## Notes

- **阻擋項：0 項（已清零）**。原 3 項皆於 2026-11-19 「追加決定（阻擋項 Q-102／Q-107／Q-115）」答覆：Q-102（預設 30 分鐘、可調）、Q-107（PO 明確承擔，附使用約束）、Q-115（解讀確認＋試跑對象規則；實作路徑拆為不阻擋的 Q-122）。
- **Status 選 Draft 的理由**：SKILL 規定 Blocked 僅在仍有阻擋項／必要檢查未完成時使用，現已清零故不再 Blocked；Ready 要求所有核取框完成且有 Accepted 套件，但 product-spec 尚未 Accepted（缺 PO 明確 Accept 與驗收證據），故維持 Draft。
- 已因追加決定解決：Q-101（還原 PO 原確認範圍）、Q-106（手動少量轉寫納入 MVP）；新增已答 Q-119、Q-120、Q-121；追加決定二（Q-103／Q-104 調查後）：Q-103 已答（三類判斷規則）；Q-104 改為待審閱、**不阻擋 Accept**（守門數字改相對敘述，PO 審閱時確認）。
- 非阻擋 Open：Q-104（待審閱確認）、Q-105、Q-108～Q-114、Q-116～Q-118、Q-122。Open 總數 13（Q-104、Q-105、Q-108～Q-114、Q-116～Q-118、Q-122），其中阻擋 0。
- 兩個 Spec Kit 輸入包皆為 Draft；product-spec.md 為 In Review（待 PO 明確 Accept），Accepted 欄位為 N/A，未簽核。
- 勾選說明：標 N/A 者因目前無 Accepted 套件而不適用，待包 Accepted 時才須檢查；其餘未勾者為真正待辦。
- 本草稿由 Claude 起草；SRC-002 為整理稿，請 PO 審閱時核對決定是否與原意一致。
- 未建立 `specs/`、未寫 `.specify/feature.json`、未改 raw/、未寫程式、未發出任何網路請求。
