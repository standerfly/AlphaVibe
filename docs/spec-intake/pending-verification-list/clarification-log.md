# Clarification Log: Pending Verification List

**Feature Slug:** pending-verification-list
**Last Updated:** 2026-08-27

這份構想是 PO 主動列出討論範圍、明確表示「不要預設答案」——以下 Q-001~
Q-005 是把 PO 原文的 5 個討論方向轉成結構化決策點，每題附上依據既有 KB
schema（`poc/kb-mcp/kb_store.py`）查證後整理出的選項，供 PO 挑選或提出
其他方向。Q-006 是查證案例素材時發現的落差，屬 non-blocking 但一併記錄。

| ID | Question / Conflict | Source IDs | Impact Area | Status | Answer / Decision | Decision Owner / Date |
|----|---------------------|------------|--------------|--------|--------------------|------------------------|
| Q-001 | 資料模型：待觀察項目的欄位/結構要做到多完整？(A) 輕量：判斷內容＋觸發條件文字＋預期時間點＋狀態(pending/resolved/dropped)，接近 comments 表加幾個結構化欄位；(B) 完整：拆分 trigger_type(date/event)、trigger_date、trigger_condition_text、target_value(如「毛利率75%」)、resolution(驗證結論文字)、resolved_at 等，形成完整「判斷→觸發→結果」軌跡；(C) 這次先不定欄位，pre-spec 只定義必要語意，schema 留給 Spec Kit 階段設計 | 001 | data | Answered | **(B) 完整**——判斷→觸發→結果全軌跡，含 trigger_type/trigger_date/trigger_condition_text/target_value/resolution/resolved_at | Stander / 2026-08-27 |
| Q-002 | 跟既有 KB 概念（`stock_themes`／`comments`／`position_plans`）的關係：(A) 全新獨立表（如 `pending_verifications`），用 code 關聯既有股票資料，不改動既有三表；(B) 延伸 `comments` 表：加 trigger_date/status 等欄位，把待觀察當成 comments 的特殊子類型；(C) 延伸 `stances` 表：待觀察視為 stance 的一種變形，沿用既有 `entry_condition`/`time_horizon` 欄位承載，不建新表 | 001 | data, workflow | Answered | **(A) 全新獨立表**，不改動既有三表；`code` 為可選外鍵（案例顯示待觀察項目常橫跨多檔股票/整條供應鏈，不強制綁單一 code，見 Q-001 選 B 後的欄位設計備註） | Stander / 2026-08-27 |
| Q-003 | 觸發/提醒機制要做到多主動？(A) 被動查閱：只做清單頁面，使用者自行篩選「已過期未驗證」項目，無主動推播；(B) 首頁被動提醒：STND首頁新增區塊顯示「已到期/即將到期」項目，沿用現有頁面瀏覽模式，不需新排程/通知基礎設施；(C) 主動排程掃描＋通知：比照 `market_scan.py` 每日排程模式另開排程，並建立目前 STND 尚不存在的主動通知機制 | 001 | workflow, integration | Answered | **(B) 首頁被動提醒**——STND首頁新增區塊顯示已到期/即將到期項目，不建排程/通知基礎設施 | Stander / 2026-08-27 |
| Q-003a | （Q-003 追加子題）首頁區塊要包含就地操作（登記/標記解決），還是只負責顯示？選項：純顯示不能操作／可就地標記已解決（不填結論）／完整管理介面（新增/編輯/填結論/瀏覽歷史，比照「資產」分頁規模） | 001 | workflow, data | Answered | **純顯示，不能就地操作**——登記與標記解決（含填 resolution 結論）均透過 Claude／MCP tool 在對話中完成，首頁區塊只負責讀取顯示，不建管理表單 UI | Stander / 2026-08-27 |
| Q-004 | 產生來源，現階段做到哪一步？(A) 純手動：使用者/Claude 在對話中明確呼叫登記，MVP 僅此；(B) 手動為主，但設計時預留「未來可能從研究筆記自動抽取待觀察句型」的擴充空間，這次不做抽取本身；(C) 手動＋研究流程慣例：這次順便把「Claude 完成研究筆記看到『待驗證』句型時主動建議登記」寫進相關 skill/CLAUDE.md 使用慣例（非程式自動化，是協作習慣） | 001 | scope, workflow | Answered | **(B)+(C)**——MVP 僅手動登記（透過 Claude／MCP tool，呼應 Q-003a），設計時預留未來自動抽取的擴充空間但這次不做；同時把「Claude 完成研究筆記看到『待驗證』句型時主動建議登記」寫進協作慣例（非程式自動化） | Stander / 2026-08-27 |
| Q-005 | 現階段（STND骨架擴充中，roadmap 已完成 1f+，module G 規劃中）是否該現在排入開發？換句話說：product-spec 定案並 Accept 後，要不要緊接著產出 spec-kit-inputs、直接交給 speckit-specify 進入技術規格與實作階段？(A) 現在就排；(B) 先定基線不排時程（比照 `alphavibe` feature 目前狀態，Accepted 但尚未排入 Spec Kit）；(C) 僅記錄構想，這次先停在 Draft/In Review 不急著 Accept | 001 | scope | Answered | **(A) 現在就接下去做**——product-spec Accept 後緊接著產出 spec-kit-inputs，交給 speckit-specify | Stander / 2026-08-27 |

### Q-005 規模估算（Codex 回應 PO 反問，2026-08-27）

依 Q-001（完整欄位）＋Q-002（全新獨立表）＋Q-003（首頁被動提醒）已定案
的組合，推估開發範圍：

- **資料層**（`poc/kb-mcp/kb_store.py`）：新增 1 張表
  `pending_verifications`（約 12 個欄位，含 code 可選外鍵）＋約 4 個
  方法（save／list／get／resolve，比照既有 `save_stance`/`save_comment`
  風格）＋隨 `_migrate()` 機制的欄位遷移（沿用既有模式，非新機制）
- **MCP 工具層**（`poc/kb-mcp/server.py`）：新增對應 3-4 個 MCP tool
  函式，讓 Claude 在研究對話中能直接登記/查詢/標記解決——這是
  Actors 段落裡「Claude 協助登記」的必要接點，不是可選項
- **後端**（`app/`）：新增 1 個 router（`pending_verifications.py`，
  約 3 個 endpoint：create／list（支援 due/overdue 篩選）／resolve），
  掛進 `app/main.py`
- **前端**（`web/`）：`Home.jsx` 新增一個區塊（顯示已到期/即將到期
  項目，含跳轉/標記解決的最小互動）；**是否需要獨立的完整管理頁面
  （新增/編輯/瀏覽全部歷史）目前未定——見下方待確認**
- **測試**：`app/tests/test_smoke.py` 補對應案例（比照既有新表上線
  前例的深度比對測試）

**規模比較**：比「資產」分頁（5張新表＋完整CRUD頁面＋導覽項目）明顯小，
接近「單一新表＋單一輕量UI區塊」的量級，不需要新的排程/通知基礎設施
（因 Q-003 選 B）。**待確認**：首頁區塊要不要能直接在上面標記
「已解決＋填結論」，還是只能導去別的地方操作（例如純靠 Claude/MCP
工具登記與結案，UI 只負責顯示）？這會影響前端工作量是否要再往上加一
個小管理介面，答案會回填進本節與 Q-004。

**時機判斷**（Codex 建議，非決定）：這個規模不依賴 module G（策略績效
回顧，roadmap 1g 尚未開始），彼此獨立；且是 PO 本人在真實研究工作流中
已重複遇到的痛點，不是假設性需求。建議 Q-005 選 (A) 現在排入開發，除非
PO 認為目前有其他更高優先序的工作在排。
| Q-006 | PO 原文提到案例見「第八節和第十二節」，查證後 `docs/research/2026-08-25-nvidia-ai-chain-pricing.md` 目前僅到第十一節，無第十二節，8/26 財報公布後的回頭驗證內容尚未寫回該文件（第8.1節「屆時應更新此節」的提醒也尚未兌現）。是否需要另外請 PO/Claude 回頭補完該研究筆記的財報後驗證段落？（與本 pre-spec 範圍無直接關係，僅一併確認） | 002 | observability | Deferred | **先不用**，不是這次範圍——維持研究筆記現況不動，待未來需要時再另外處理 | Stander / 2026-08-27 |
