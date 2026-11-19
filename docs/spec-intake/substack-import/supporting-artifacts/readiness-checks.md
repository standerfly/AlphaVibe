# Dynamic Readiness Checks: Substack 文章自動匯入（011）

**Feature Slug:** substack-import
**Last Updated:** 2026-11-19（追加決定後修訂）

「Complete」＝文件已撰寫，不代表其中 Open 項已解決；Open 項見 clarification-log.md B 節與下方 Gap 表。

## Feature Traits

| Feature Trait | Detected | Required Artifact Or Section | Status | Link | Rationale |
|---------------|----------|------------------------------|--------|------|-----------|
| Multi-role, multi-system, or multi-step workflow | Yes | Workflow diagram or sequence diagram | Complete | workflow-and-state-model.md（第 1、2 節 mermaid 流程圖與循序圖） | 排程／即時取得／手動轉寫 → 鎖 → feed → 去重 → 寫庫 → 圖片 → 通知，多步驟多角色；已補實際圖 |
| Async job, callback, event handling, or state transition | Yes | Sequence diagram and state transition model | Complete | workflow-and-state-model.md（第 2 節循序圖、第 3 節文章狀態圖、第 4 節圖片狀態圖）、schedule-and-locks.md | 每日排程批次＋排程與即時取得並行；文章與圖片有狀態轉換，已補狀態轉換圖 |
| New or changed external/internal API behavior | Yes | API contract or API design note | Complete | permission-security-note.md（第 1、6、7 節） | 新增即時取得寫入工具、既有搜尋／讀取工具行為擴充、與 010 唯讀守門關係、逾時風險、來源可信度標示；欄位級合約留待 plan |
| Third-party or cross-system integration | Yes | Integration note, data mapping, timeout/retry semantics, and failure behavior | Complete | integration-note.md | Substack 公開 RSS；含逾時、ETag、403／429 退避、失敗行為；部分數值待規格 |
| New or changed data lifecycle | Yes | Data model note, retention rule, migration note, or compatibility note | Complete | data-model-note.md | 新增獨立 `substack.db` 與圖片目錄；方案 C 與 010 隔離、舊庫相容、回滾；保留期限未決（Q-114） |
| Permission, role, or approval behavior | Yes | Permission matrix or approval flow | Complete | permission-security-note.md | 新增寫入型 MCP 工具之權限、唯讀白名單排除、PO 親自確認範圍（登入／鑰匙圈／消耗用量／安裝排程） |
| Security, privacy, compliance, or audit concern | Yes | Security/privacy requirements and audit expectations | Complete | permission-security-note.md（第 4、5 節） | 不登入／不用 cookie／不繞付費牆、日誌不含標題、外洩掃描、ToS 灰色地帶（Q-107） |
| Import, export, or batch processing | Yes | Validation rules, partial failure policy, and recovery behavior | Complete | error-handling-matrix.md（第 1、2、4 節） | 每日批次匯入、首次回補；部分失敗政策與恢復路徑已定 |
| High-risk, irreversible, payment, order, or control flow | No | N/A | N/A | N/A | 唯讀抓取公開 feed，無下單、付款或不可逆動作；寫入限於可由還原備份回復的 `substack.db`，去重保證重跑安全（以 guid／URL），故不另需補償機制；冪等性已寫於 FR-005 |
| Operationally sensitive behavior | Yes | Observability, alerting, and manual recovery note | Complete | error-handling-matrix.md（第 3、4 節） | 無人值守排程、被站方封鎖風險、硬碟空間現況回報、手動恢復 |

## Missing Artifact Gaps

| Gap ID | Artifact | Blocking? | Needed Decision Or Content | Owner | Status |
|--------|----------|-----------|----------------------------|-------|--------|
| GAP-001 | 排程授權與每次執行確認的解讀 | No | Q-101 已答（追加決定第1題） | Stander | Closed |
| GAP-002 | 即時取得最小間隔數值 | Yes | Q-102 | Stander | Open |
| GAP-003 | 付費預覽判斷規則 | No | Q-103 已答（三類規則；追加決定二） | Stander | Closed |
| GAP-004 | 遠端分支與工具數守門 | No | Q-104 待審閱確認（守門數字改相對敘述；不阻擋 Accept） | Stander | Open |
| GAP-005 | 手動轉寫的 PO 解讀確認與實作路徑 | Yes | Q-106 已答；解讀確認與路徑見 Q-115 | Stander／規格階段 | Open |
| GAP-006 | ToS 風險承擔書面記錄 | Yes | Q-107 | Stander | Open |
| GAP-007 | 23:00／23:40 搶庫日誌結果 | No | Q-105 | Stander／Claude | Open |
| GAP-008 | 備份與健檢納入範圍、feed 延遲、圖片細節、雙庫搜尋識別 | No | Q-108～Q-114 | Stander | Open |
| GAP-009 | 逾時秒數、作者間隔、告警門檻、補跑規則等數值 | No | 規格階段補 | Claude／Stander | Open |
| GAP-010 | token 排程間隔『過短』數值；手動 token 工作是否受時窗限制；即時取得逾時機制 | No | Q-117、Q-116、Q-118 | Stander／規格階段 | Open |
