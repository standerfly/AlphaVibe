# Extracted Requirements: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

## 問題陳述（Source: 001）

研究/分析工作流裡反覆出現一種結構：一個判斷或假設，附帶「等到某個未來
時間點或事件發生，就能驗證/更新這個判斷」的但書。目前這種但書只能寫成
自然語言散文（例：`comments`／研究筆記 markdown），沒有結構化欄位存放
「觸發條件是什麼、預期何時發生、現在驗證了沒」，也沒有任何機制在時間到
時主動讓使用者或系統重新注意到它——完全依賴人記得回頭查閱。案例見
Source 002：NVIDIA Q2 FY2027 財報（2026/8/26）作為驗證漲價後毛利率是否
守住的關鍵時間點，這句話被寫在研究筆記的判讀段落裡，財報公布後（查證
時點 2026-08-27）尚未被回頭確認或更新（見 Source 002 查證備註）。

## Candidate Functional Requirements

- FR-C01：使用者（或 Claude 代使用者）能登記一筆「待觀察項目」，記錄
  判斷內容與其驗證所依賴的觸發條件/預期時間點。（Source: 001）
- FR-C02：待觀察項目能與既有 KB 概念（標的 code、stock_theme、既有
  comments 或 position_plan 之一或多個）建立關聯，而非完全孤立存在。
  （Source: 001，關聯方式待 PO 決定，見 clarification-log Q-002）
- FR-C03：待觀察項目要有可查詢/可瀏覽的清單呈現方式，讓使用者能看到
  「哪些項目已到預期時間點但尚未驗證」。（Source: 001，呈現形式/主動
  程度待 PO 決定，見 clarification-log Q-003）
- FR-C04：待觀察項目要有狀態欄位，區分「待驗證」「已驗證/已有結論」
  「已過期未追蹤」等狀態（狀態集合待細化）。（Source: 001, 推論自問題
  陳述「時間到了會主動浮現」的需求）
- FR-C05：待觀察項目驗證後，要能記錄驗證結果/結論，形成「判斷 → 觸發
  → 驗證結果」的完整軌跡，而不是驗證完就結案消失。（Source: 001，推論
  自 Source 002 案例——PO 期待的是「回頭確認並更新」，不只是提醒）

## Candidate Actors And User Goals

- **PO/TPM（Stander）**：在研究/分析對話中，隨手登記一個「這件事之後要
  回頭驗證」的判斷；之後在需要時（或系統主動提示時）能看到所有待驗證
  項目，尤其是已到期但還沒驗證的。（Source: 001）
- **Claude（研究協作者）**：在研究工作流中識別出「待驗證」句型時，可能
  需要協助登記（手動觸發，見 clarification-log Q-004），以及在被問到
  「XX 現在有答案了嗎」時能查詢到對應項目。（Source: 001, 推論）

## Candidate Success Criteria

- 待觀察項目一旦登記，其觸發條件與預期時間點是結構化資料，可被程式
  查詢（不再只存在於 markdown 散文裡）。（Source: 001，可測量：能否寫
  SQL/API query 撈出「已過期未驗證」清單）
- 案例重跑：若本功能存在，Source 002 的 NVIDIA Q2 FY2027 財報案例應該
  在 2026/8/26（或之後首次查閱清單時）被使用者看到「待驗證」提示，而
  不是要等到使用者自己想起來去查研究筆記。（Source: 001+002，作為驗收
  情境的具體案例，非正式驗收標準——待 product-spec 階段轉為 Acceptance
  Scenario）

## Candidate Constraints And Assumptions

- 假設：本功能定位是「個人使用」（單一使用者 Stander），沿用現有 STND
  local-first、無多使用者權限機制的既有假設。（Source: 001, 推論自
  CLAUDE.md 專案定位；未經 PO 明確確認，見 clarification-log）
- 假設：不涉及股價/財報等外部資料的即時抓取——待觀察項目本身只是「使用
  者的判斷/假設」的結構化記錄，「觸發條件是否已滿足」目前假設仍是人工
  判斷（使用者自己看新聞/財報後回來標記完成），除非 PO 選擇更主動的
  掃描方向（見 clarification-log Q-003 選項C）。
- 約束：現有 KB 資料層是 SQLite（`poc/kb-mcp/kb_store.py`），STND 後端
  是 FastAPI 直接 import 既有函式（`app/` 不重寫商業邏輯）——若本功能
  進入 Spec Kit 階段，預期會遵循同樣的分層方式（新增/延伸 kb_store.py
  的表與方法，`app/` 新增對應 router）。（Source: 查證 CLAUDE.md +
  poc/kb-mcp/kb_store.py）

## Candidate Error Or Failure Behavior

Q-003 已定案為(B)首頁被動提醒（不建排程/通知基礎設施），錯誤情境因此
較少，主要是一般 CRUD 層級的失敗處理：

- 登記/查詢/標記解決透過 Claude／MCP tool 進行（Q-004），任一筆缺必填
  欄位（判斷內容、觸發條件、預期時間點）應拒絕寫入並回傳明確錯誤，不
  應靜默失敗——比照既有 `save_stance`/`save_comment` 的錯誤處理風格。
- 首頁區塊查詢「已到期/即將到期」清單時，若查詢本身失敗（如資料庫連線
  問題），比照既有頁面既有的優雅降級模式（顯示錯誤提示，不擋其他首頁
  內容渲染），不需要新發明一套機制。

## Duplicates, Conflicts, And Unclear Statements

| ID | Source IDs | Type | Statement | Status | Notes |
|----|------------|------|-----------|--------|-------|
| GAP-001 | 001 | Unclear | PO 提出的5個討論方向（資料模型/關聯/觸發機制/產生來源/現階段是否該做）皆未預設答案 | Resolved | 已轉為 clarification-log Q-001~Q-005（另加 Q-003a 子題），PO 已於 2026-08-27 全數回答：Q-001=B(完整欄位)、Q-002=A(全新獨立表)、Q-003=B(首頁被動提醒)、Q-003a=純顯示不可就地操作、Q-004=B+C(手動為主+協作慣例)、Q-005=A(現在排入開發) |
| GAP-002 | 002 | Conflict/Discrepancy | PO 原文稱案例見「第八節和第十二節」，查證後 `docs/research/2026-08-25-nvidia-ai-chain-pricing.md` 目前僅到第十一節，無第十二節，也未見財報公布後的回頭更新內容 | Answered | 已記錄於 raw/001、raw/002 查證備註；不影響構想成立性，反而是問題陳述的佐證，見 clarification-log Q-006 |
