# Clarification Log: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

這份構想是 PO 主動列出討論範圍、明確表示「不要預設答案」——以下 Q-001~
Q-005 是把 PO 原文的 5 個討論方向轉成結構化決策點，每題附上依據既有 KB
schema（`poc/kb-mcp/kb_store.py`）查證後整理出的選項，供 PO 挑選或提出
其他方向。Q-006 是查證案例素材時發現的落差，屬 non-blocking 但一併記錄。

| ID | Question / Conflict | Source IDs | Impact Area | Status | Answer / Decision | Decision Owner / Date |
|----|---------------------|------------|--------------|--------|--------------------|------------------------|
| Q-001 | 資料模型：待觀察項目的欄位/結構要做到多完整？(A) 輕量：判斷內容＋觸發條件文字＋預期時間點＋狀態(pending/resolved/dropped)，接近 comments 表加幾個結構化欄位；(B) 完整：拆分 trigger_type(date/event)、trigger_date、trigger_condition_text、target_value(如「毛利率75%」)、resolution(驗證結論文字)、resolved_at 等，形成完整「判斷→觸發→結果」軌跡；(C) 這次先不定欄位，pre-spec 只定義必要語意，schema 留給 Spec Kit 階段設計 | 001 | data | Blocking | TBD | TBD |
| Q-002 | 跟既有 KB 概念（`stock_themes`／`comments`／`position_plans`）的關係：(A) 全新獨立表（如 `pending_verifications`），用 code 關聯既有股票資料，不改動既有三表；(B) 延伸 `comments` 表：加 trigger_date/status 等欄位，把待觀察當成 comments 的特殊子類型；(C) 延伸 `stances` 表：待觀察視為 stance 的一種變形，沿用既有 `entry_condition`/`time_horizon` 欄位承載，不建新表 | 001 | data, workflow | Blocking | TBD | TBD |
| Q-003 | 觸發/提醒機制要做到多主動？(A) 被動查閱：只做清單頁面，使用者自行篩選「已過期未驗證」項目，無主動推播；(B) 首頁被動提醒：STND首頁新增區塊顯示「已到期/即將到期」項目，沿用現有頁面瀏覽模式，不需新排程/通知基礎設施；(C) 主動排程掃描＋通知：比照 `market_scan.py` 每日排程模式另開排程，並建立目前 STND 尚不存在的主動通知機制 | 001 | workflow, integration | Blocking | TBD | TBD |
| Q-004 | 產生來源，現階段做到哪一步？(A) 純手動：使用者/Claude 在對話中明確呼叫登記，MVP 僅此；(B) 手動為主，但設計時預留「未來可能從研究筆記自動抽取待觀察句型」的擴充空間，這次不做抽取本身；(C) 手動＋研究流程慣例：這次順便把「Claude 完成研究筆記看到『待驗證』句型時主動建議登記」寫進相關 skill/CLAUDE.md 使用慣例（非程式自動化，是協作習慣） | 001 | scope, workflow | Blocking | TBD | TBD（Codex 建議：B 是常見安全預設——MVP手動、預留擴充空間、不現在做抽取，除非 PO 認為 C 的協作慣例現在就想要） |
| Q-005 | 現階段（STND骨架擴充中，roadmap 已完成 1f+，module G 規劃中）是否該現在排入開發？(A) 現在就排：product-spec Accept 後直接產出 spec-kit-inputs，進 Spec Kit 階段；(B) 先定基線不排時程：product-spec 寫完並 Accept，暫不建立 spec-kit-inputs，之後再排優先序（比照 `alphavibe` feature 目前狀態）；(C) 僅記錄構想：這次先停在 Draft/In Review，不急著 Accept，留待下次討論 | 001 | scope | Blocking | TBD | TBD |
| Q-006 | PO 原文提到案例見「第八節和第十二節」，查證後 `docs/research/2026-08-25-nvidia-ai-chain-pricing.md` 目前僅到第十一節，無第十二節，8/26 財報公布後的回頭驗證內容尚未寫回該文件（第8.1節「屆時應更新此節」的提醒也尚未兌現）。是否需要另外請 PO/Claude 回頭補完該研究筆記的財報後驗證段落？（與本 pre-spec 範圍無直接關係，僅一併確認） | 002 | observability | Non-blocking | TBD | TBD |
