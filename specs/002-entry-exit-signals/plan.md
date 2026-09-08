# Implementation Plan: 進出場訊號層（門檻、背離偵測與主動提醒）

**Branch**: `002-entry-exit-signals` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)
**Depends On**: `specs/001-entry-exit-foundation/`（階段A，已實作並驗收）

## Summary

在階段A 的損益與價位計算之上，補齊「訊號層」：討論式停損停利門檻、
基本面與價格背離偵測、營收趨勢判斷擴大、觸發時的調整建議，並讓這些
訊號在既有的每日流程中自動產生、在既有的三個呈現面自動出現。

技術路線的核心是**零新增外部呼叫**——三種新訊號的資料全部來自既有已
載入或已快取的來源（現價快取、營收年增率快取、股價歷史快取），因此
不會重演階段A 那次「排程慢 29 分鐘」的問題。

## Technical Context

**Language/Version**: Python 3.9（本機唯一版本）
**Primary Dependencies**: 無新增；重用階段A 的 `pnl.py`／`price_position.py`
**Storage**: SQLite，**新增一張表** `exit_thresholds`（append-only），
其餘沿用既有表、不改 schema
**Testing**: `unittest`，`python3 -m unittest discover -s poc/kb-mcp/tests`；
一律 `tempfile` 獨立庫（**絕不碰 `poc/data/`**）
**Target Platform**: 本機 macOS，MCP stdio server ＋ FastAPI/React 前端
**Project Type**: 單一專案，商業邏輯集中在 `poc/kb-mcp/`
**Performance Goals**: 每日流程**不得顯著增加執行時間**，基準線
39 檔 1097 秒（18.3 分）——新訊號設計為零新增外部呼叫，預期增幅
僅為本機計算（毫秒級）
**Constraints**: 不即時查外部 API；不重寫既有商業邏輯的介面；
不寫入 `stances`；門檻設定工具不得進唯讀白名單
**Scale/Scope**: 39 檔（持股 ∪ 觀察名單）、每日一次批次

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` 仍是未填寫的樣板（全欄位 placeholder），
沿用階段A 的做法，改以專案 `CLAUDE.md` 的硬約束做等效檢查：

| 關卡 | 狀態 | 依據 |
|---|---|---|
| Python 3.9 相容 | ✅ 設計未用 3.10+ 語法 | CLAUDE.md 2026-07-07 教訓 |
| `poc/kb-mcp/` 零外部依賴 | ✅ 不新增套件 | CLAUDE.md 硬約束 |
| 不重寫既有商業邏輯 | ⚠️ **一處例外，已論證**：FR-007 要求擴大營收趨勢判斷準則，`_growth_deceleration` 的**內部演算法**會改變，但**輸出契約與呼叫端介面不變**（research.md R-004）。這是規格明文要求的改動，非順手重寫 | spec FR-007 |
| 不碰正式資料庫 | ✅ 測試用暫存庫；新表以 `CREATE TABLE IF NOT EXISTS` 建立 | CLAUDE.md 2026-08-22 教訓 |
| 外部呼叫成本要實測 | ⏳ 實作時必做（見下方觀測性節） | 階段A 教訓／spec FR-012 |
| 驗證不自驗 | ⏳ 實作完成後派 fresh agent 驗收 | `~/.claude/rules/10-model-dispatch.md` |
| 繁體中文介面與文件 | ✅ | CLAUDE.md |

## Project Structure

### Documentation (this feature)

```text
specs/002-entry-exit-signals/
├── plan.md              # 本檔
├── spec.md              # 需求（15 條 FR，16/16 檢核通過）
├── research.md          # Phase 0：9 項查證與取捨
├── data-model.md        # Phase 1：新表 schema、記憶體結構、狀態判定順序
├── quickstart.md        # Phase 1：怎麼跑、怎麼驗
├── contracts/
│   └── mcp-tools.md     # Phase 1：2 個新工具＋既有 API 的欄位變更
└── checklists/
    └── requirements.md  # spec 品質檢核（16/16）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── exit_signals.py           # 新增：門檻判斷＋背離偵測＋營收趨勢（純函式）
├── kb_store.py               # 修改：exit_thresholds 表＋4 個存取方法
├── review_engine.py          # 修改：run_module_d_review 產出新 items；
│                             #       _growth_deceleration 委派給 exit_signals.revenue_trend
├── module_d_scheduler.py     # 修改：log 加時間戳與逐階段耗時（FR-012 量測基礎）
├── report.py                 # 修改：_chart_stats_html 支援兩種口徑並存
├── server.py                 # 修改：TOOLS +2、dispatch +2
├── server_readonly.py        # 修改：白名單只加 get_exit_threshold
└── tests/
    ├── test_exit_signals.py  # 新增：門檻/背離/趨勢的各情境
    ├── test_traceability.py  # 修改：登記 FR-001~FR-015、工具數 45→47
    └── test_report.py        # 修改：兩種口徑並存的渲染斷言

app/routers/stock_detail.py   # 修改：holdings 區塊新增 fifo／cost_method_label
web/src/pages/StockDetail.jsx # 修改：兩種口徑的呈現
```

**不動的檔案**（明文列出以免誤改）：`pnl.py`、`price_position.py`
（階段A 產物，只讀取不修改）、`holdings_sync.py`、`screener.py`、
`twse_price_client.py`、`finmind_client.py`。

## 實作順序

1. **`kb_store` 的 `exit_thresholds` 表 ＋ 4 個存取方法** ＋ 測試——最底層
2. **`exit_signals.py` 的三個純函式** ＋ 測試（門檻判斷、營收趨勢、背離）
   ——不碰 I/O，最好測；先寫測試再實作
3. **`_growth_deceleration` 委派** ＋ **正式資料的改動前後比對**
   （research.md R-004 要求，不可只跑單元測試）
4. **MCP 工具註冊三處** ＋ 守門測試（含「寫入工具不得進白名單」的反向斷言）
5. **每日流程整合** ＋ **外部呼叫次數實測**（有無新訊號的呼叫次數必須相同）
6. **`module_d_scheduler` log 時間戳**（FR-012 的量測基礎，要先於第 7 步）
7. **頁面兩種口徑並存**（`report.py` → `app/routers/` → React 三層）
8. **traceability 登記** ＋ 完整回歸 ＋ **fresh agent 獨立驗收**

## 觀測性與失敗降級

**1. 外部呼叫次數的實測（FR-012 的核心，不可省略）**

實作第 5 步後必須做：攔截 `twse_price_client._throttled_get` 與
`finmind_client` 的請求函式，分別在「關閉新訊號」與「開啟新訊號」兩種
情況下跑同一批標的，**呼叫次數必須完全相同**。階段A 的教訓是「從參數
語意推論呼叫次數」會錯，所以這裡只接受實測數字。

**2. 排程耗時的可觀測性（R-009）**

`module_d_scheduler.py` 目前的 log 完全沒有時間戳，本次基準線只能從
`module_d_results.checked_at` 反推。要能驗證 FR-012，得先讓 log 印出
起訖時間與逐階段耗時。

**3. 失敗降級（FR-011）**

新訊號的任何例外都不得影響既有檢查項目——每個新訊號在
`run_module_d_review` 內各自 try 包住，失敗時產出一筆
`status=error` 的 item 並繼續，比照階段A `compute_all_positions` 的做法
（`pnl.py:152-`）。既有的通用層/策略層/老芋頭層檢查完全不受影響。

**4. 洗版控制（R-006）**

只有實際觸發的訊號才填 `suggested_action`（那是首頁「今日重點」的篩選
條件）。未設定門檻、未觸發、資料不足一律不填，避免首頁被灌爆。

## Complexity Tracking

| 項目 | 為何需要 | 較簡單的替代方案為何不夠 |
|---|---|---|
| 新增 `exit_thresholds` 表而非重用 `position_plans` | 語意不同（出場門檻 vs 加碼額度），且需要歷史 | 塞進 `position_plans` 會讓一張表承載兩種語意，且該表是覆寫式沒有歷史 |
| `_growth_deceleration` 改為委派 | FR-007 明文要求擴大判斷期數 | 另開獨立檢查會讓同一件事出現兩個矛盾結果 |
| 頁面同時顯示兩種損益口徑 | PO 裁決 Q2-C，避免 1/3 標的突然空白 | 單純替換是可見的每日退步；單純保留舊值則沒解決一致性問題 |

**無其他複雜度豁免**——三種訊號都是查詢時即算的純函式，不做快取表、
不做非同步、不新增外部資料源。
