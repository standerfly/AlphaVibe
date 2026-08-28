# Product Spec: Pending Verification List

**Status:** Accepted
**Feature Slug:** pending-verification-list
**Function Branch:** 本次以 `--no-branch` 初始化，未另建
`function/pending-verification-list` 分支——本 session 由 Claude Code 遠端
執行環境指派固定於 `claude/watchlist-feature-discussion-uzo3ga` 分支工作
（`develop` 分支尚未建立，比照既有已知現況見 CLAUDE.md），若後續進入
Spec Kit 階段，由 `speckit-specify` 依當時慣例另行建立工作分支
**Product Owner:** Stander
**TPM:** Stander
**Accepted At:** 2026-08-27
**Acceptance Evidence:** PO Stander 於 2026-08-27 本 Claude Code session
中，在完成全部 clarification-log.md Q-001~Q-005（含 Q-003a）決定並審閱
完整規格內容後，於 AskUserQuestion 回覆「核准（Accept）」明確核准本
需求基線

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

**目標**：讓「待驗證的判斷」有結構化的存放位置（新增獨立資料表），並在
觸發條件成立時能被使用者在 STND 首頁看到，取代目前「寫進散文、靠人
記得」的現況。MVP 範圍聚焦在登記與被動顯示，不建自動抽取或主動通知。

## Business Context And Priority

- Priority: 現在排入開發（clarification-log.md Q-005=A，PO 於
  2026-08-27 決定）
- Timing: 緊接在本 product-spec Accept 後產出 spec-kit-inputs，交給
  `speckit-specify` 進入技術規格與實作階段；不依賴 STND roadmap 的
  module G（策略績效回顧，尚未開始）
- Business value: 減少「已埋下但沒人記得回頭驗證的判斷」造成的分析品質
  風險——PO 本人在研究工作流中已實際遇到此問題不只一次（Source: 001）

## Actors

- **PO/TPM（Stander）**：在研究/分析對話中請 Claude 登記「這件事之後要
  回頭驗證」的判斷；之後打開 STND 首頁就能看到已到期/即將到期的待驗證
  項目，需要時再請 Claude 查詢細節/標記解決
- **Claude（研究協作者）**：透過 MCP tool 在對話中登記、查詢、標記解決
  待觀察項目；在完成研究筆記時若識別出「待驗證」句型，主動建議登記
  （協作慣例，非程式自動化）；被問到「XX 現在有答案了嗎」時查詢對應項目

## MVP Scope

### In Scope

- 新增獨立資料表 `pending_verifications`（欄位定義見下方「資料模型與
  狀態轉換」章節），記錄判斷內容、觸發條件、預期時間點、狀態、驗證結論
  的完整軌跡
- MCP tool：登記（save）、查詢（list，支援依狀態/到期與否篩選）、取得
  單筆（get）、標記解決（resolve，寫入 resolution 與 resolved_at）
- `app/` 新增對應 router，供 STND 首頁呼叫查詢 API
- STND 首頁新增一個純顯示區塊：列出「已到期／即將到期」的待觀察項目
  （status=pending 且 trigger_date 已到或接近），不含任何就地操作按鈕
- 協作慣例：於相關 skill／CLAUDE.md 記錄「Claude 完成研究筆記識別出
  『待驗證』句型時，主動建議登記」的使用習慣

### Out Of Scope

- 從研究對話自動抽取「待觀察」句型的 NLP/自動化機制本身（只確保資料
  模型/API 設計不擋死未來擴充，這次不寫抽取程式）
- 首頁區塊的就地操作 UI（新增/編輯/標記解決的表單）——一律透過 Claude／
  MCP tool 完成
- 主動排程掃描與推播/email 等通知基礎設施——STND 目前無此類基礎設施，
  這次也不新建
- 多使用者/角色權限機制——沿用 STND 現有個人單一使用者假設

### Deferred

- 若未來發現「只靠 Claude／MCP tool 操作」不夠用，可再評估獨立管理頁面
  （比照「資產」分頁規模）——視為新一輪構想討論，不預先排進本次範圍
- 研究筆記自動抽取「待觀察」句型的機制——待未來需求明確後另開構想討論

## 資料模型與狀態轉換

新增表 `pending_verifications`（`poc/kb-mcp/kb_store.py`，沿用既有
`SCHEMA`/`_migrate()` 機制，不改動既有 `stock_themes`/`comments`/
`position_plans` 三表）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| code | TEXT，可為 NULL | 可選：待觀察項目常橫跨多檔股票或整條供應鏈（例：NVIDIA 漲價案例牽動記憶體/ODM/電力多檔），不強制綁單一標的 |
| theme | TEXT，可為 NULL | 可選：對應既有 `stock_themes` 的主題文字，供分類/查詢，不建外鍵約束 |
| judgment_text | TEXT NOT NULL | 判斷/假設內容本身 |
| trigger_type | TEXT NOT NULL | `date`（時間點觸發）或 `event`（事件觸發） |
| trigger_date | TEXT，可為 NULL | 預期時間點（`trigger_type=date` 時應填；`event` 時可留空或填預估區間） |
| trigger_condition_text | TEXT NOT NULL | 觸發條件的文字描述（例：「NVIDIA 公布 Q2 FY2027 財報」） |
| target_value | TEXT，可為 NULL | 可選：具體驗證目標（例：「毛利率75%」） |
| status | TEXT NOT NULL | `pending`／`resolved`／`dropped`，預設 `pending` |
| resolution | TEXT，可為 NULL | 驗證結論文字，`status=resolved` 時應填 |
| resolved_at | TEXT，可為 NULL | 標記解決的時間戳 |
| source_ref | TEXT，可為 NULL | 來源引用（比照既有 `stances`/`comments`/`snapshots` 慣例） |
| created_at | TEXT NOT NULL | |
| updated_at | TEXT NOT NULL | |

**狀態轉換規則**：
- 新建項目一律從 `pending` 開始
- `pending → resolved`：呼叫 resolve，需同時提供 `resolution` 文字，系統
  寫入 `resolved_at`
- `pending → dropped`：使用者判斷這個待觀察項目不再需要追蹤（例如判斷
  本身已不成立、或事後認為不重要），不需要 `resolution`，但建議仍可填
  一句話說明原因（沿用 `resolution` 欄位承載，語意上代表「為何不追蹤了」
  而非「驗證結論」）
- `resolved`／`dropped` 為終態，不可逆——若要重新追蹤，登記一筆新項目
  （比照 `stances` 用多筆歷史列而非改寫既有列的既有模式）

## Functional Requirements

- **FR-001**：使用者（或 Claude 代使用者）能透過 MCP tool 登記一筆待
  觀察項目，必填欄位為 `judgment_text`、`trigger_type`、
  `trigger_condition_text`；`trigger_type=date` 時 `trigger_date` 亦為
  必填
- **FR-002**：能查詢待觀察項目清單，支援依 `status` 篩選，以及「已到期
  但仍為 pending」（`trigger_date` ≤ 今天 且 `status=pending`）的篩選
  條件
- **FR-003**：能標記一筆待觀察項目為 `resolved`（需提供 `resolution`）
  或 `dropped`
- **FR-004**：STND 首頁新增一個區塊，顯示「已到期／即將到期」（自行
  定義的視窗期，如 7 天內）且 `status=pending` 的待觀察項目，純顯示、
  無就地操作
- **FR-005**（協作慣例，非程式邏輯）：Claude 完成研究筆記時若識別出
  「待驗證」句型，主動向使用者建議是否要登記為待觀察項目

## Acceptance Scenarios

1. 使用者在研究對話中請 Claude 登記「NVIDIA 2026/8/26 公布 Q2 FY2027
   財報，用來驗證漲價是否守住 75% 毛利率」——登記後應可查詢到這筆
   `pending` 狀態的項目，`trigger_date=2026-08-26`
2. 2026/8/26 後，使用者打開 STND 首頁，應能在新區塊看到上述項目被列為
   「已到期」（因為 `trigger_date` 已過、`status` 仍是 `pending`）
3. 使用者請 Claude 查證財報結果後，請 Claude 將該筆項目標記為
   `resolved`，附上驗證結論——之後首頁區塊不再顯示這筆項目（因
   `status` 已非 `pending`），但透過 MCP tool 查詢歷史仍可見完整記錄
4. 使用者登記一筆判斷後，若之後認為這個判斷不重要，可請 Claude 標記為
   `dropped`——首頁區塊同樣不再顯示

## Success Criteria

- 待觀察項目的觸發條件與預期時間點是結構化資料，可被程式查詢（不再只
  存在於 markdown 散文裡）——可測量：能否查詢出「已過期未驗證」清單
- STND 首頁能實際顯示「已到期/即將到期」項目，不需使用者自己想起來去
  翻研究筆記——可測量：對照 Acceptance Scenario 2 的具體案例是否成立
- 標記解決後的項目仍可被追溯查詢（不是刪除），形成完整判斷軌跡——可
  測量：`resolved`/`dropped` 項目透過 MCP tool 仍可查得

## Constraints And Assumptions

- 假設：本功能定位為個人使用（單一使用者 Stander），沿用 STND
  local-first、無多使用者權限機制的既有假設，與現有
  `stances`/`comments`/`position_plans` 前例一致
- 約束：現有 KB 資料層是 SQLite（`poc/kb-mcp/kb_store.py`），STND 後端
  FastAPI（`app/`）直接 import 既有函式、不重寫商業邏輯——本功能進入
  Spec Kit 階段預期遵循同樣分層方式
- 約束：`develop` 分支尚未建立（已知現況，見 CLAUDE.md），若後續要走
  `function/<slug>` 分支慣例，需先與 PO 確認補建 develop 或改用
  `--no-branch`
- 約束：首頁區塊的「即將到期」視窗期（例如 7 天）等具體 UI 參數留給
  Spec Kit 階段依實作細節決定，本文件不預先鎖定

## Dependencies

- 不依賴 STND roadmap 其他進行中項目（module G 尚未開始，彼此獨立）
- 依賴 `poc/kb-mcp/kb_store.py` 既有的 `_migrate()` 欄位遷移機制與既有
  MCP server（`poc/kb-mcp/server.py`）的 tool 註冊模式

## Error Handling Requirements

| Failure Case | Expected Product Behavior | User/System Feedback | Recovery Path | Blocking? |
|--------------|---------------------------|----------------------|---------------|-----------|
| 登記時缺必填欄位（judgment_text/trigger_type/trigger_condition_text，或 trigger_type=date 卻缺 trigger_date） | 拒絕寫入，不建立資料列 | MCP tool 回傳明確錯誤訊息，說明缺哪個欄位 | 使用者/Claude 補齊欄位後重新呼叫 | 否（單筆失敗不影響其他資料） |
| 標記 resolved 卻未提供 resolution | 拒絕狀態轉換 | 回傳錯誤，要求補 resolution | 補上 resolution 後重試 | 否 |
| 首頁區塊查詢待觀察清單時資料庫查詢失敗 | 顯示錯誤提示，不擋其他首頁內容渲染 | 首頁區塊顯示簡短錯誤訊息（比照既有頁面優雅降級模式） | 使用者重新整理頁面；若持續失敗需人工查證資料庫狀態 | 否 |

## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
| Readiness Checks | Yes | Complete | supporting-artifacts/readiness-checks.md | Required by ADR-0027 |
| Data model note | Yes | Complete | 本文件「資料模型與狀態轉換」章節 | 新增資料生命週期，見 readiness-checks.md（已 Closed） |
| 狀態轉換模型 | Yes | Complete | 本文件「資料模型與狀態轉換」章節 | pending/resolved/dropped 等狀態轉換，見 readiness-checks.md（已 Closed） |

## Source Decisions

- 問題陳述、5 個討論方向：Source 001（PO 對話逐字構想提出，2026-08-27）
- 案例佐證：Source 002（`docs/research/2026-08-25-nvidia-ai-chain-pricing.md`
  第156-157、207-208行；查證發現 PO 提到的「第十二節」目前不存在，見
  clarification-log.md Q-006，non-blocking，不影響本規格）
- 範圍決策：clarification-log.md Q-001~Q-005、Q-003a，全數由 PO Stander
  於 2026-08-27 本 session 中直接回答，詳見 `scope-decision.md`
