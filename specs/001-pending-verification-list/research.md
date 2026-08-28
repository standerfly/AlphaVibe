# Research: Pending Verification List

**Phase 0 output** — Technical Context 在本次規劃中沒有留下
`NEEDS CLARIFICATION` 標記（見 `plan.md`），因為技術棧與既有架構模式在
pre-spec 階段已經查證清楚（`docs/spec-intake/pending-verification-list/
product-spec.md` 已包含資料模型與約束）。本文件記錄幾個仍值得寫下決策
理由的技術選擇，供後續 `/speckit.tasks`／實作階段參考，不是「解決未知」
而是「把已經確定的選擇記錄下來，附上為什麼」。

## 決策 1：資料儲存方式

**Decision**：新增獨立 SQLite 表 `pending_verifications`（
`poc/kb-mcp/kb_store.py`），比照既有 `stances`／`snapshots`／
`position_plans` 等表的風格（`CREATE TABLE IF NOT EXISTS` 進
`SCHEMA` 常數，遷移欄位走既有 `_migrate()`／`_MIGRATIONS` 機制）。

**Rationale**：PO 已在 pre-spec 階段明確決定（`clarification-log.md`
Q-002=A），且技術上這是風險最低的做法——不動既有表結構，不影響既有查詢
與既有頁面渲染。

**Alternatives considered**：
- 延伸 `comments` 表（FTS5 虛擬表）：FTS5 虛擬表不易再加結構化查詢欄位
  （如依 `trigger_date` 篩選、依 `status` 篩選），要另外維護一張輔助表
  才能做到，複雜度反而更高，PO 已否決此案。
- 延伸 `stances` 表：語意不合——`stances` 是「每檔股票的目前立場」
  （latest-wins 模型），待觀察項目不強制綁單一股票、也不是「立場」，
  硬塞會混淆兩種概念，PO 已否決此案。

## 決策 2：MCP tool 整合方式

**Decision**：延伸 `poc/kb-mcp/server.py` 既有的 `TOOLS` 清單（純
標準庫 stdio JSON-RPC 實作，見 `server.py` 檔案開頭 docstring），新增
4 個 tool schema（`save_pending_verification`／
`list_pending_verifications`／`get_pending_verification`／
`resolve_pending_verification`），並在既有 dispatch 邏輯
（`if name == "save_stance": ...` 的同一個 if/elif 鏈）新增對應分支。

**Rationale**：這是本 repo 唯一的 MCP 介接方式，本機只有 Python 3.9、
官方 MCP SDK 需 3.10+，既有選擇是不依賴 SDK 的純標準庫實作——沿用同一
套機制，不引入新依賴、不破壞既有 3.9 相容性約束。

**Alternatives considered**：另開一個獨立 MCP server 處理待觀察項目
——不必要的複雜度，既有 server 已經是「多能力工具集中在一個 stdio
server」的設計，沒有理由為單一功能另開一個。

## 決策 3：STND 首頁區塊的資料抓取方式

**Decision**：`Home.jsx` 新增一個獨立的 `fetch`（呼叫新 router 的
`GET .../due` 或帶查詢參數的 list endpoint），比照既有 `dashboard` 與
`holdings` 兩個區塊「各自獨立 fetch、各自 loading/error、互不阻塞」的
既有模式（見 `Home.jsx` 檔案開頭註解）。

**Rationale**：這是 `Home.jsx` 唯一的既有模式，維持一致性；也符合
product-spec.md 的錯誤處理要求（首頁區塊查詢失敗不擋其他內容渲染）。

**Alternatives considered**：把待觀察清單塞進既有 `/api/dashboard`
回應——會讓 `dashboard.py` router 承擔不相關的職責（待觀察項目跟
`dashboard.py` 現有的「今日重點/候選」邏輯是不同的資料來源與查詢條件），
違反既有分層習慣（各 router 對應各自獨立的資料關注點，見
`app/routers/` 底下既有檔案一支 router 一個關注點的慣例）。

## 決策 4：測試策略

**Decision**：`poc/kb-mcp/kb_store.py` 新方法用 `unittest` 補單元測試
（比照 `poc/kb-mcp/tests/` 既有慣例）；`app/tests/test_smoke.py` 補
新 router 的深度比對測試，且**必須包含併發測試**（比照 2026-08-22
教訓紀錄——`get_kb_store()` 是 FastAPI sync generator dependency，由
anyio thread pool 執行，同一 request 的建立/關閉不保證同一條 thread，
新表若沒測併發很可能上線後才發現 race）。

**Rationale**：這是本 repo 血淋淋換來的既有教訓（見 CLAUDE.md
2026-08-22 兩則教訓紀錄），不是理論風險——上一次新表上線（資產分頁）
真的因為沒測併發，正式環境 30 個 request 有 23 個 500。

**Alternatives considered**：只測依序單一請求——上一輪已證明不夠，
不採用。

## 決策 5：首頁「已到期／即將到期」視窗期

**Decision**：預設 7 天（`trigger_date` 已過，或未來 7 天內），實作為
router 端一個常數／可選 query 參數，不寫死進前端。

**Rationale**：spec.md 的 Assumptions 已記錄此為合理預設、非阻斷性
決策，7 天是常見的「近期待辦」慣例窗口，且實作上容易之後調整（改一個
常數，不影響資料模型或 API 形狀）。

**Alternatives considered**：只顯示「已過期」不含「即將到期」——會讓
使用者永遠是「事後」才看到提醒，喪失部分「主動看到」的價值（NVIDIA
案例裡，PO 若能在財報公布前幾天就看到「即將到期」，比財報公布後才看到
「已過期」更有用）；因此保留即將到期窗口。
