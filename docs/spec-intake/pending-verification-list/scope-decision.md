# Scope Decision: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

PO 已於 2026-08-27 回答 clarification-log.md 全部 Q-001~Q-005（另加
Q-003a 子題），範圍定案如下。

## MVP In Scope

- 新增獨立資料表 `pending_verifications`（Q-002=A），記錄「判斷→觸發→
  結果」完整軌跡（Q-001=B）：判斷內容、`code`（可選，不強制單一標的）、
  trigger_type（date/event）、trigger_date、trigger_condition_text、
  target_value（可選）、status（pending/resolved/dropped）、resolution
  （驗證結論文字）、resolved_at、source_ref、created_at/updated_at
- Claude／MCP tool 登記與查詢介面（save/list/get/resolve，Q-004 手動為
  主），供使用者在研究對話中隨手登記、之後查詢
- STND 首頁新增一個純顯示區塊，列出「已到期/即將到期」的待觀察項目
  （Q-003=B），**不含就地操作**（Q-003a）——登記與標記解決一律透過
  Claude／MCP tool 完成
- 協作慣例：Claude 在研究筆記中識別出「待驗證」句型時，主動建議登記
  （Q-004 的 C 部分），寫進相關 skill／CLAUDE.md 使用慣例，非程式自動化

## Out Of Scope

- 從研究對話自動抽取「待觀察」句型的 NLP/自動化機制本身（Q-004 明確
  排除，只預留欄位/API 設計空間，這次不做抽取程式）
- 首頁區塊的就地操作 UI（新增/編輯/填結論表單）——Q-003a 已排除，全部
  透過 Claude／MCP tool 操作
- 主動排程掃描與推播/email 等通知基礎設施——Q-003 已排除，STND 目前無
  此類基礎設施，這次也不新建
- 多使用者/角色權限機制——沿用 STND 現有個人單一使用者假設

## Deferred Or Later

- 若使用習慣顯示「只靠 Claude／MCP tool 操作」不夠用（例如需要離開對話
  也能直接在網頁上登記/編輯），屆時可再評估要不要加一個獨立管理頁面
  （比照「資產」分頁規模）——這次不做，且未來若要做應視為新一輪 pre-spec
  討論，不預先排進本次範圍
- 研究筆記自動抽取「待觀察」句型的機制——待未來需求明確後另開構想討論

## Split Feature Decisions

| Spec Feature Slug | Scope Summary | Dependencies | Handoff Order | Status |
|-------------------|---------------|--------------|---------------|--------|
| pending-verification-list | 單一 Spec Kit 輸入套件：`pending_verifications` 新表＋MCP tool＋首頁純顯示區塊；範圍小、無需拆分 | 無外部依賴，不依賴 module G（策略績效回顧，roadmap 1g 尚未開始） | 1 | Draft |

## Decision Rationale

| Decision | Source IDs | Owner | Date | Rationale |
|----------|------------|-------|------|-----------|
| Q-001 選(B) 完整欄位 | 001 | Stander | 2026-08-27 | PO 直接決定，要完整的「判斷→觸發→結果」軌跡，不只是輕量提醒 |
| Q-002 選(A) 全新獨立表 | 001 | Stander | 2026-08-27 | PO 直接決定，不改動既有 stock_themes/comments/position_plans 三表 |
| Q-003 選(B) 首頁被動提醒 | 001 | Stander | 2026-08-27 | PO 直接決定，不建排程/通知基礎設施 |
| Q-003a 選「純顯示」 | 001 | Stander | 2026-08-27 | PO 直接決定，規模最小，登記/解決都走 Claude／MCP tool |
| Q-004 選(B)+(C) | 001 | Stander | 2026-08-27 | PO 直接決定，MVP手動為主、預留擴充空間，同時把識別「待驗證」句型主動建議登記寫進協作慣例 |
| Q-005 選(A) 現在排入開發 | 001 | Stander | 2026-08-27 | PO 直接決定，依 Codex 提供的規模估算（新增1表、少量MCP tool、1個router、首頁1個純顯示區塊）判斷規模小、不依賴 module G，值得現在做 |
| 排除自動抽取本身於 MVP 之外 | 001 | Stander | 2026-08-27 | Q-004 最終決定確認：預留擴充空間但這次不做抽取程式本身 |
