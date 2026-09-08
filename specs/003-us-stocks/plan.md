# Implementation Plan: 美股獨立投資系統

**Branch**: `003-us-stocks` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-us-stocks/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

在 STND（AlphaVibe 對外服務品牌）新增一個獨立的「美股」分頁：交易截圖匯入、
股價走勢圖＋買賣點位、研究筆記／投資立場記錄、關注條件監控＋Telegram推播。
技術路線：延續既有 `app/`（FastAPI，HTTP轉接層）＋`web/`（React，STND既有
設計系統）＋`poc/kb-mcp/`（演算法/儲存層）三層架構，但美股的儲存與查詢管道
**完全獨立於既有台股系統**——新增獨立的 `USStockStore`、獨立 db 檔案
`us_stocks.db`、獨立一組 MCP 工具，不修改、不共用任何既有台股程式碼或資料。
排程模式比照既有 `market_scan.py`（launchd 每日觸發），交易截圖辨識沿用
既有「agent 讀圖轉文字→工具解析文字」模式（不新增 OCR 依賴）。詳細技術
決策依據見 `research.md`。

## Technical Context

**Language/Version**: Python 3.9+（後端，比照本 repo 既有環境限制——這台
開發機只有 Python 3.9.6，`prespec_init.py` 曾因用到 3.10+ 語法而崩潰，見
CLAUDE.md 教訓紀錄）；JavaScript（React 18.3，既有 `web/` 前端）
**Primary Dependencies**: FastAPI（既有 `app/`，沿用不新增框架）；React 18.3
+ Vite 5 + react-router-dom（既有 `web/`，沿用不新增框架）；新增：FMP／
備援報價API的 HTTP client（函式庫沿用 `finmind_client.py`／
`twse_price_client.py` 既有慣例，確切函式庫名稱待實作時查看該兩檔確認，
見 `research.md` §5，non-blocking）
**Storage**: 全新獨立 SQLite 檔案 `poc/data/us_stocks.db`（`USStockStore`，
`poc/kb-mcp/us_stock_store.py`），不與 `alphavibe.db`／`KBStore` 共用任何
程式碼或表（`research.md` §1）
**Testing**: Python `unittest`，比照 `poc/kb-mcp/tests/` 既有慣例（新增
`poc/kb-mcp/tests/test_us_stock_store.py` 等）；若新增 FastAPI router，
比照 `app/tests/test_smoke.py` 的深度比對模式（不只測 HTTP 200，比對底層
函式輸出）
**Target Platform**: 現有 Mac Mini 常駐服務（launchd + uvicorn + ngrok），
新增一個獨立的 launchd 排程（`com.alphavibe.usstockscan.plist`，比照
`com.alphavibe.marketscan.plist` 模式，不進版控、直接部署在使用者機器上）
**Project Type**: Web service（延伸既有 `app/` + `web/` 架構，不新建
`backend/`／`frontend/` 目錄結構）
**Performance Goals**: 個人單一使用者規模，非公開服務等級——沿用 STND
既有非正式標準（頁面互動流暢即可，無嚴格 SLA／併發要求）
**Constraints**:
- 不得修改、不得共用既有 `KBStore`／`alphavibe.db`／既有
  `mcp__alphavibe-kb__*` 系列 MCP 工具（spec.md FR-015/016）
- 排程頻率僅每日一次（spec.md FR-006 第三輪決定），額度用盡的降級處理
  必須沿用既有「單位獨立 try/except、不中斷其他單位、寫入 error/skip
  狀態而非拋例外」模式（`research.md` §4）
- 交易截圖辨識**不需要**OCR/圖像處理程式碼——比照既有4個匯入工具
  （`parse_holdings_report`等）的純文字解析模式，辨識由 Claude 多模態
  能力在對話中完成，MCP 工具只接受文字輸入（`research.md` §3）
- 視覺呈現延續 STND 既有設計系統（`web/src/styles/tokens.css`／
  `app.css`／`StockComboChart.jsx`），不建立新視覺語言
**Scale/Scope**: 單一使用者，追蹤股票數預估數十檔以內；4張新資料表，
9個新MCP工具，1個新排程腳本，1組新前端頁面（landing/詳情/匯入/研究筆記）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**本 repo 沒有已批准的專案憲章**：`.specify/memory/constitution.md` 是
從未填寫過的樣板（全部欄位仍是 `[PLACEHOLDER]`），這個 repo 從未執行過
`/speckit.constitution`。因此本節**如實記錄此狀態，不假造原則來源**，也
不虛構一份「事後合理化」的憲章。

改以本 repo **既有的實際架構慣例**作為事實上的一致性檢查標準（非正式
Constitution，但是可查證的既有先例）：

| 既有慣例 | 本計畫是否遵循 |
|---|---|
| `app/` 只做 HTTP 轉接層，不重寫商業邏輯，import `poc/kb-mcp/*.py` | ✅ 遵循——新 router 直接 import `USStockStore`／`us_stock_mcp_server.py` |
| 演算法/儲存邏輯放 `poc/kb-mcp/` | ✅ 遵循——`us_stock_store.py`／`us_stock_scan.py`／`us_stock_mcp_server.py` 皆放此處 |
| 排程靠 launchd，不用常駐 Python 排程套件 | ✅ 遵循——新增獨立 plist，比照 `market_scan.py` |
| 外部 API 呼叫失敗要優雅降級，不拋例外中斷其他項目 | ✅ 遵循，見 `research.md` §4 |
| 前端沿用既有設計系統，不另建視覺語言 | ✅ 遵循 |
| 資料庫寫入副作用不掛在建構子（2026-08-22 資產表教訓） | ✅ 遵循——`USStockStore` 不會有任何隱式種子寫入邏輯掛在 `__init__` |

**Gate 結果**：PASS（無違反既有慣例之處，無需 Complexity Tracking 的例外
說明）。

## Project Structure

### Documentation (this feature)

```text
specs/003-us-stocks/
├── plan.md              # 本檔案
├── research.md          # Phase 0 輸出
├── data-model.md         # Phase 1 輸出
├── quickstart.md         # Phase 1 輸出
├── contracts/
│   └── mcp-tools.md       # Phase 1 輸出
└── tasks.md              # Phase 2 輸出（由 /speckit.tasks 產生，本檔案不建立）
```

### Source Code (repository root)

延伸既有 `app/` + `web/` + `poc/kb-mcp/` 三層架構，不新建
`backend/`／`frontend/` 目錄（本 repo 從未使用該種結構）：

```text
poc/kb-mcp/
├── us_stock_store.py          # 新增：USStockStore類別，獨立schema/db
├── us_stock_scan.py           # 新增：每日排程CLI入口，比照market_scan.py
├── us_stock_mcp_server.py     # 新增：獨立MCP server，9個工具
├── us_stock_price_client.py   # 新增：FMP+備援來源的HTTP client
└── tests/
    ├── test_us_stock_store.py       # 新增
    └── test_us_stock_scan.py        # 新增

poc/data/
└── us_stocks.db                # 新增：獨立db檔案（gitignore，比照alphavibe.db）

app/routers/
└── us_stocks.py                # 新增：FastAPI router，import自us_stock_store.py

app/tests/
└── test_smoke.py               # 修改：新增美股router的深度比對測試

web/src/pages/
├── UsStocks.jsx                 # 新增：美股landing頁
├── UsStockDetail.jsx             # 新增：個股詳情頁
└── UsStockImport.jsx             # 新增：交易截圖匯入頁

web/src/components/
├── AppShell.jsx                  # 修改：TABS常數新增「美股」項目
└── UsStockResearchNote.jsx       # 新增：研究筆記渲染元件（FR-005/009）
```

**Structure Decision**：延伸既有三層架構（`app/`轉接層／`web/`前端／
`poc/kb-mcp/`演算法儲存層），美股專屬程式碼在每一層都用獨立檔案/模組
存放（不與台股共用檔案），但**不**另開獨立的 top-level 目錄——這樣既
滿足 FR-015/016 的「資料/查詢管道獨立」要求，又維持與既有 repo 慣例
一致的檔案組織方式，降低未來維護者要在兩套不同結構間切換的認知負擔。

## Complexity Tracking

> 本計畫沒有 Constitution Check 違規需要說明（見上方 Gate 結果：PASS），
> 此節留空。
