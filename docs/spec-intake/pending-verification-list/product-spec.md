# Product Spec: Pending Verification List

**Status:** Draft
**Feature Slug:** pending-verification-list
**Function Branch:** 本次以 `--no-branch` 初始化，未另建
`function/pending-verification-list` 分支——本 session 由 Claude Code 遠端
執行環境指派固定於 `claude/watchlist-feature-discussion-uzo3ga` 分支工作
（`develop` 分支尚未建立，比照既有已知現況見 CLAUDE.md），若後續進入
Spec Kit 階段，由 `speckit-specify` 依當時慣例另行建立工作分支
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** N/A
**Acceptance Evidence:** N/A

## Problem And Goal

研究/選股分析工作流裡反覆出現一種結構：一個判斷或假設，附帶「等到某個
未來時間點或事件發生，就能驗證/更新這個判斷」的但書。目前這種但書只能
寫成自然語言散文，沒有結構化欄位存放「觸發條件是什麼、預期何時發生、
現在驗證了沒」，也沒有機制在時間到時主動讓使用者重新注意到它——完全
依賴人記得回頭查閱。

案例（見 `docs/research/2026-08-25-nvidia-ai-chain-pricing.md` 第156-157、
207-208行）：NVIDIA 2026/8/26 公布的 Q2 FY2027 財報被寫下是「驗證這次
漲價是否守住毛利率的第一個關鍵時間點」，這句判讀停留在研究筆記的散文
段落，財報公布後（查證時點 2026-08-27）尚未被回頭確認或更新到該筆記——
連文中自己寫下「屆時應更新此節」提醒的段落都未被兌現。

**目標**：讓「待驗證的判斷」有結構化的存放位置，並在觸發條件成立時能被
使用者看到，取代目前「寫進散文、靠人記得」的現況。**具體達成方式（欄位
範圍、與既有 KB 概念的關係、觸發機制的主動程度、產生來源）尚待 PO 決定
——見 `clarification-log.md` Q-001~Q-005，本節的問題陳述已確定，Goal
的實作邊界待補。**

## Business Context And Priority

- Priority: TBD（待 Q-005 決定：現在排入開發／先定基線不排時程／僅記錄
  構想）
- Timing: TBD（同上，另涉及 STND roadmap 現況——1f+ 已完成、module G
  規劃中，見 `docs/spec-intake/alphavibe/roadmap.md`）
- Business value: 減少「已埋下但沒人記得回頭驗證的判斷」造成的分析品質
  風險——PO 本人在研究工作流中已實際遇到此問題不只一次（Source: 001）

## Actors

- **PO/TPM（Stander）**：在研究/分析對話中登記「這件事之後要回頭驗證」
  的判斷；之後需要時能看到所有待驗證項目，尤其是已到期但還沒驗證的
- **Claude（研究協作者）**：在研究工作流中識別出「待驗證」句型時協助
  登記（互動方式待 Q-004 決定），並在被問到「XX 現在有答案了嗎」時能
  查詢對應項目

## MVP Scope

### In Scope

- 待補——待 Q-001~Q-004 的 PO 決定後填入（見 `scope-decision.md`）

### Out Of Scope

- 從研究對話自動抽取「待觀察」句型的 NLP/自動化機制本身（即使預留擴充
  空間，這次不做抽取，見 `scope-decision.md` Decision Rationale）
- 多使用者/角色權限機制——沿用 STND 現有個人單一使用者假設

### Deferred

- 主動排程掃描＋通知機制（若 Q-003 選到這個方向，規模較大、可能需要
  拆成獨立 spec-kit-inputs 套件，晚於基本登記/查詢功能交付）

## Functional Requirements

- 待補——見 `extracted-requirements.md` 的 FR-C01~FR-C05（候選需求，
  需 Q-001~Q-004 決定後轉為正式、可測試的 FR）

## Acceptance Scenarios

1. 待補——待範圍決定後補上正式驗收情境；候選驗收案例（非正式標準）：
   NVIDIA Q2 FY2027 財報案例——若本功能存在，該筆待觀察項目應在
   2026/8/26 之後、使用者下次查閱清單時，被標示為「已到期待驗證」

## Success Criteria

- 待觀察項目的觸發條件與預期時間點是結構化資料，可被程式查詢（不再只
  存在於 markdown 散文裡）——可測量：能否查詢出「已過期未驗證」清單
- 其餘待 Q-001~Q-003 決定後補充可測量的具體指標

## Constraints And Assumptions

- 假設：本功能定位為個人使用（單一使用者 Stander），沿用 STND
  local-first、無多使用者權限機制的既有假設（未經 PO 明確逐條確認，
  但與現有 `stances`/`comments`/`position_plans` 前例一致）
- 約束：現有 KB 資料層是 SQLite（`poc/kb-mcp/kb_store.py`），STND 後端
  FastAPI（`app/`）直接 import 既有函式、不重寫商業邏輯——若進入 Spec
  Kit 階段，預期遵循同樣分層方式
- 約束：`develop` 分支尚未建立（已知現況，見 CLAUDE.md），若後續要走
  `function/<slug>` 分支慣例，需先與 PO 確認補建 develop 或改用
  `--no-branch`

## Dependencies

- 依賴 Q-001~Q-005 的 PO 決定才能定案範圍與 FR（見 `clarification-log.md`）
- 若 Q-002 選擇延伸既有表（`comments` 或 `stances`），需另外評估對既有
  功能（Layer 2/3 既有查詢、`report.py` 既有頁面渲染）的相容性影響

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 待補 | 待 Q-003 決定觸發機制後補充——若選被動查閱（A/B），錯誤情境很少；若選主動排程掃描（C），需定義掃描失敗/漏掃的處理方式，比照 `market_scan.py`/`benchmark.py` 既有優雅降級模式 | TBD | TBD | TBD |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Draft | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| Data model note | Required, pending Q-001/Q-002 | Open | 待補（可併入本文件章節） | 新增/延伸資料生命週期，見 readiness-checks.md GAP-001 |
| 狀態轉換模型 | Required, pending Q-001 | Open | 待補 | pending/resolved/dropped 等狀態轉換，見 readiness-checks.md GAP-002 |
| Integration/observability note | Conditional on Q-003 | Open | 待補 | 僅當選擇主動排程掃描時需要，見 readiness-checks.md GAP-003 |

## Source Decisions

- 問題陳述、5 個討論方向：Source 001（PO 對話逐字構想提出，2026-08-27）
- 案例佐證：Source 002（`docs/research/2026-08-25-nvidia-ai-chain-pricing.md`
  第156-157、207-208行；查證發現 PO 提到的「第十二節」目前不存在，見
  clarification-log.md Q-006）
