# Spec Kit Input: Pending Verification List

**Status:** Draft
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** pending-verification-list
**Handoff Order:** 1

## Feature Summary

新增一個結構化的「待觀察／待驗證判斷」機制：使用者（或代其操作的
Claude）在研究/分析對話中登記一筆「帶有觸發條件與預期時間點的判斷」，
系統以獨立資料表儲存完整「判斷→觸發→結果」軌跡，並在 STND 首頁純顯示
「已到期／即將到期」的待驗證項目，取代目前只能寫成 markdown 散文、靠人
記得回頭查閱的現況。

## Actors

- **PO/TPM（Stander）**：在研究/分析對話中請 Claude 登記待驗證判斷；
  打開 STND 首頁查看已到期/即將到期項目；需要時請 Claude 查詢/標記解決
- **Claude（研究協作者）**：透過 MCP tool 登記、查詢、標記解決待觀察
  項目；完成研究筆記時識別出「待驗證」句型可主動建議登記（協作慣例）

## In Scope

- 新增 `poc/kb-mcp/kb_store.py` 資料表 `pending_verifications`（欄位
  定義見「Functional Requirements」章節的資料模型描述）
- `poc/kb-mcp/server.py` 新增 MCP tool：登記（save）、查詢（list，支援
  依 status／到期與否篩選）、取得單筆（get）、標記解決（resolve）
- `app/` 新增對應 router，供前端查詢已到期/即將到期清單
- `web/src/pages/Home.jsx` 新增一個純顯示區塊，列出「已到期／即將到期」
  且 `status=pending` 的項目，無就地操作按鈕
- 於相關 skill／CLAUDE.md 記錄協作慣例：Claude 完成研究筆記識別出
  「待驗證」句型時主動建議登記

## Out Of Scope

- 從研究對話自動抽取「待觀察」句型的 NLP/自動化機制本身
- 首頁區塊的就地操作 UI（新增/編輯/標記解決表單）
- 主動排程掃描與推播/email 等通知基礎設施
- 多使用者/角色權限機制

## User Scenarios

1. 使用者在研究對話中請 Claude 登記「NVIDIA 2026/8/26 公布 Q2 FY2027
   財報，用來驗證漲價是否守住 75% 毛利率」——登記後可查詢到這筆
   `pending` 狀態的項目，`trigger_date=2026-08-26`
2. 2026/8/26 後，使用者打開 STND 首頁，能在新區塊看到上述項目被列為
   「已到期」
3. 使用者請 Claude 查證財報結果後，將該筆項目標記為 `resolved`，附上
   驗證結論——首頁區塊不再顯示，但透過 MCP tool 查詢歷史仍可見完整記錄
4. 使用者認為某判斷不再重要，請 Claude 標記為 `dropped`——首頁區塊同樣
   不再顯示

## Functional Requirements

- **FR-001**：能透過 MCP tool 登記一筆待觀察項目，必填
  `judgment_text`、`trigger_type`（`date`/`event`）、
  `trigger_condition_text`；`trigger_type=date` 時 `trigger_date` 亦為
  必填。缺必填欄位時拒絕寫入並回傳明確錯誤
- **FR-002**：能查詢待觀察項目清單，支援依 `status` 篩選，以及「已到期
  但仍為 pending」（`trigger_date` ≤ 今天 且 `status=pending`）的篩選
  條件
- **FR-003**：能將一筆待觀察項目標記為 `resolved`（需提供
  `resolution`）或 `dropped`；`resolved`/`dropped` 為終態，不可逆——要
  重新追蹤需登記新項目（比照既有 `stances` 用多筆歷史列而非改寫既有列
  的模式）
- **FR-004**：STND 首頁新增區塊，顯示「已到期／即將到期」（視窗期，如
  7 天內，具體參數由實作階段決定）且 `status=pending` 的項目，純顯示、
  無就地操作
- **FR-005**（協作慣例，非程式邏輯）：Claude 完成研究筆記時若識別出
  「待驗證」句型，主動向使用者建議是否登記為待觀察項目

### 資料模型（`pending_verifications` 表）

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| code | TEXT，可為 NULL | 可選，不強制綁單一標的（待觀察項目常橫跨多檔股票/整條供應鏈） |
| theme | TEXT，可為 NULL | 可選，對應既有 `stock_themes` 的主題文字，不建外鍵約束 |
| judgment_text | TEXT NOT NULL | 判斷/假設內容 |
| trigger_type | TEXT NOT NULL | `date` 或 `event` |
| trigger_date | TEXT，可為 NULL | 預期時間點 |
| trigger_condition_text | TEXT NOT NULL | 觸發條件文字描述 |
| target_value | TEXT，可為 NULL | 可選，具體驗證目標 |
| status | TEXT NOT NULL | `pending`／`resolved`／`dropped`，預設 `pending` |
| resolution | TEXT，可為 NULL | 驗證結論或不追蹤原因 |
| resolved_at | TEXT，可為 NULL | 標記解決的時間戳 |
| source_ref | TEXT，可為 NULL | 來源引用 |
| created_at | TEXT NOT NULL | |
| updated_at | TEXT NOT NULL | |

不改動既有 `stock_themes`／`comments`／`position_plans` 三表，沿用既有
`SCHEMA`/`_migrate()` 遷移機制。

## Success Criteria

- 觸發條件與預期時間點是結構化資料，可被程式查詢
- STND 首頁能顯示「已到期/即將到期」項目（對照 User Scenario 2）
- `resolved`/`dropped` 項目仍可透過 MCP tool 追溯查詢，不是刪除

## Constraints And Assumptions

- 個人單一使用者（Stander），沿用 STND local-first、無角色權限機制假設
- 沿用現有分層：`poc/kb-mcp/kb_store.py`（資料層＋MCP tool）→ `app/`
  （FastAPI router，直接 import 既有函式，不重寫商業邏輯）→ `web/`
- `develop` 分支尚未建立（已知現況）；若走 `function/<slug>` 分支慣例，
  需先與 PO 確認補建 develop 或改用 `--no-branch`
- 首頁「即將到期」視窗期等具體 UI 參數留給實作階段決定

## Source Decisions

- `../../product-spec.md`（Accepted，2026-08-27）
- `../../clarification-log.md` Q-001~Q-005、Q-003a（全數由 PO Stander於
  2026-08-27 本 session 直接回答）
- `../../scope-decision.md`（MVP In/Out/Deferred Scope、Split Feature
  Decisions）
