# Implementation Plan: 機票掃描分頁

**Branch**: `005-flight-scan-page` | **Date**: 2026-09-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/005-flight-scan-page/spec.md`

## Summary

在 STND 新增「機票」分頁，讓使用者以粗略條件（目的地、候選外站、出發區間、
行程天數、兩端間隔策略、排除月份）取得依價格排序的外站四段票組合，**日期由
系統抽樣產生而非使用者指定**。

技術路線：**不重寫任何查價或行程枚舉演算法**。`poc/kb-mcp/flight_search.py`
（2,018 行、112 測試）與 `poc/kb-mcp/scraper/`（Node + Playwright）已完成並
經真實查價驗證，本功能是為其加上持久化的查詢條件、背景執行、進度可視化與
網頁介面。新增的程式碼集中在三處：獨立資料層、FastAPI router、React 分頁。

## Technical Context

**Language/Version**: Python 3.9.6（後端；**硬限制**，本機唯一可用版本，
不得使用 3.10+ 語法）、JavaScript ES2020＋React 18（前端）、Node 26（scraper）
**Primary Dependencies**: FastAPI（既有）、React＋Vite（既有）、
`poc/kb-mcp/flight_search.py`（既有，不修改其演算法）、Playwright（既有，
scraper 專用，不進後端）
**Storage**: SQLite 獨立資料庫 `poc/data/flights.db`，比照
`us_stock_store.py`（`us_stocks.db`）與 `photo_store.py`（`photos.db`）先例。
查價快取沿用既有 `poc/data/flight_cache/`（檔案式），不遷入 DB
**Testing**: `unittest`——資料層與服務層測試置於 `poc/kb-mcp/tests/`，
路由層納入 `app/tests/test_smoke.py`（含併發測試，見下方風險）
**Target Platform**: macOS 本機常駐（`launchd`），對外經 ngrok 固定網址；
使用者以桌機與行動裝置瀏覽器存取
**Project Type**: Web application（`app/` 後端 ＋ `web/` 前端，同源部署）
**Performance Goals**: 分頁開啟後既有結果 2 秒內可見（SC-003）；掃描為背景
作業，不阻塞請求
**Constraints**: 零金錢成本（不訂閱付費服務）；外部查價服務有速率上限且
確切值未經長期驗證；`sqlite3.connect` 必須帶 `check_same_thread=False`
（見下方風險）；不得程式化抓取 robots.txt 明文禁止的站台
**Scale/Scope**: 單一使用者；預期同時存在 1–5 個查詢條件，每條件數十筆結果；
單次掃描規模數十筆

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**狀態：無可評估的 gate。**

`.specify/memory/constitution.md` 目前是**未填寫的樣板**——所有原則名稱與
內容仍為 `[PRINCIPLE_1_NAME]`、`[PRINCIPLE_1_DESCRIPTION]` 等佔位字串，
版本欄位為 `[CONSTITUTION_VERSION]`。因此本階段沒有實質原則可檢核。

這是本專案的既有狀況，`001`～`004` 四個既有 feature 同樣在無憲章的情況下
完成。本計畫**不**假裝通過檢核，也不自行擬定憲章內容（那需要 PO 決策，
屬 `/speckit.constitution` 的範圍）。

替代的品質約束來自兩處，且皆為可檢核的具體條文：
1. 專案指南 `CLAUDE.md`：Python 3.9 相容、獨立 store／獨立 db、
   不重寫既有演算法、資料目錄防呆
2. 本 feature 的 pre-spec 基線 `docs/spec-intake/flight-search/product-spec.md`
   （Accepted）：14 項約束，含 CON-09「顯示的限制數字須標明實測或推估」、
   CON-11「不得規避封鎖」、CON-14「候選順序即偏好順序」

**建議（非本計畫範圍）**：專案若要讓 Constitution Check 有意義，應執行
`/speckit.constitution` 建立憲章。此事影響全專案而非僅本 feature，
不在此處代為決定。

## Project Structure

### Documentation (this feature)

```text
specs/005-flight-scan-page/
├── plan.md              # 本檔
├── research.md           # Phase 0 輸出
├── data-model.md         # Phase 1 輸出
├── quickstart.md          # Phase 1 輸出
├── contracts/
│   └── flights-api.md    # Phase 1 輸出（內部 HTTP 契約）
├── checklists/
│   └── requirements.md   # 規格品質檢核（已完成，16 項全過）
└── tasks.md              # Phase 2 輸出（由 /speckit.tasks 產生，非本指令）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── flight_search.py            # 既有：查價、枚舉、間隔挑選、速率守衛（不改演算法）
├── flight_store.py             # 新增：查詢條件與掃描結果的持久化（獨立 db）
├── flight_scan_service.py      # 新增：把條件轉成掃描作業、續掃、狀態推導
├── scraper/                    # 既有：Node + Playwright 查價
└── tests/
    ├── test_flight_search.py   # 既有（112 測試）
    ├── test_flight_store.py    # 新增
    └── test_flight_scan_service.py  # 新增

app/
├── flight_deps.py              # 新增：FlightStore 依賴注入（比照 us_stock_deps.py）
├── routers/
│   └── flights.py              # 新增：條件 CRUD、觸發掃描、查詢進度與結果
└── tests/
    └── test_smoke.py           # 既有：新增機票路由的深度與併發檢查

web/src/
├── pages/
│   ├── Flights.jsx             # 新增：分頁主畫面（條件卡片、結果表）
│   └── FlightTrackForm.jsx     # 新增：新增／編輯條件表單
└── components/
    └── AppShell.jsx            # 既有：新增「機票」導覽項
```

**Structure Decision**: 沿用專案既有的三層分工——演算法與資料層在
`poc/kb-mcp/`、HTTP 層在 `app/routers/`、介面在 `web/src/pages/`。這不是
本計畫新創的結構，而是 `us-stocks`（003）與 `photos`（004）兩個 feature
已建立的慣例：`app/` 的 router 直接 import `poc/kb-mcp/` 的既有函式，
不在 `app/` 內重寫商業邏輯。因此不採用範本的 `backend/`＋`frontend/`
分離樹狀結構。

## Complexity Tracking

> 憲章未建立，故無「違反憲章」可言。此處記錄本計畫刻意接受的兩項複雜度，
> 供 review 判斷是否值得。

| 複雜度 | 為何需要 | 被否決的簡單選項與原因 |
|--------|----------|----------------------|
| 新增 `flight_scan_service.py` 一層（不把邏輯放進 router） | 掃描狀態需由「枚舉組合 vs 既有快取」推導，且跨時段續掃、速率裁切、軟封鎖處理都是可獨立測試的純邏輯 | 直接寫在 router 內：無法用 `unittest` 覆蓋，且會把 HTTP 關注點與掃描邏輯綁在一起。既有 `photos.py` 把背景任務邏輯放在 router 內，在該情境可行（單次匯入），但本功能的續掃與配額邏輯複雜得多 |
| 進度不使用記憶體字典，改由快取反推 | 掃描可跨數小時、跨服務重啟（US3 情境 4 明確要求重啟後只查未完成者） | 比照 `photos.py` 用模組內記憶體字典：服務重啟即遺失進度，會違反 FR-015 與 US3 情境 4 |
