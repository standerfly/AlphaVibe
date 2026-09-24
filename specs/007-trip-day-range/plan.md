# Implementation Plan: 四段票天數區間化

**Branch**: `007-trip-day-range` | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-trip-day-range/spec.md`

## Summary

把既有已上線四段票追蹤條件（`flight-search`／`flight-price-tracking`，
specs/005、006）的行程天數從單一固定整數升級為區間（下限～上限），
系統在區間內展開多個天數選項各自查價比較；遷移正式庫既有唯一一筆
追蹤條件（id=9）到新語意並重新查價；並在建立條件時新增組合數上限
守衛，避免天數區間帶來的組合數暴增拖垮共用查詢配額。

技術路線：**不重寫既有查價與展開機制**。`flight_search.py` 的
`build_itineraries_fixed_trip()`／`sample_dates()` 本身不需要變動——
天數是呼叫端（`expand_track()`）在迴圈裡對每個天數選項各呼叫一次
既有函式即可，不是底層查價邏輯的變動。新增的程式集中在三處：
`flight_store.py` 的 schema／驗證、`flight_scan_service.py` 的
`expand_track()` 展開迴圈與新增的組合數計算／上限守衛函式、以及
`app/routers/flights.py`／前端表單的欄位形狀同步。

## Technical Context

**Language/Version**: Python 3.9.6（硬限制，本機唯一可用版本）
**Primary Dependencies**: 既有 `flight_search.py`（178 測試）、
`flight_scan_service.py`、`flight_store.py`、FastAPI／React（既有）。
**不新增任何第三方套件**
**Storage**: 沿用 `poc/data/flights.db`，`flight_track` 表需要 schema
異動（新增天數區間欄位、遷移既有 `trip_days` 資料）
**Testing**: `unittest`（`poc/kb-mcp/tests/`）＋ `app/tests/test_smoke.py`
**Target Platform**: macOS 本機，`app/` 後端 ＋ `web/` 前端，正式服務
以 `launchd` 常駐（`com.alphavibe.reportserver`）
**Project Type**: Web application（既有）
**Performance Goals**: 單一條件的組合數上限守衛需在使用者提交建立
請求後**立即**（同步驗證，不需查詢外部服務）回應拒絕或接受
**Constraints**: 查詢仍受既有速率上限約束（約 20 筆／小時，推估值）；
id=9 遷移屬於對正式生產資料的異動，需要跟過去處理正式服務異動同等
級的謹慎（migration 前備份、回歸測試、smoke test、正式環境驗證）
**Scale/Scope**: 單一使用者，正式庫目前僅 1 筆既有追蹤條件（id=9）
需要遷移

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**狀態：無可評估的 gate**（與 005、006 相同）。

`.specify/memory/constitution.md` 仍是未填寫的樣板（所有原則為
`[PRINCIPLE_N_NAME]` 佔位字串）。本計畫不假裝通過檢核，也不自行擬定
憲章內容——那需要 PO 決策，屬 `/speckit.constitution` 的範圍。

## Project Structure

### Documentation (this feature)

```text
specs/007-trip-day-range/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   └── tracks-api.md
└── tasks.md              # Phase 2 output (/speckit.tasks，本指令不建立)
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── flight_store.py            # schema／migration／驗證／CRUD（本次異動核心）
├── flight_scan_service.py     # expand_track() 展開邏輯、新增組合數計算與上限守衛
├── flight_search.py           # 既有查價函式，不變動（天數迴圈在呼叫端處理）
├── migrate_trip_days_range.py # 新增：id=9 遷移的一次性腳本（比照既有
│                               # seed_assets_once.py 的先例，一次性、
│                               # 需要人手動執行，不掛進任何自動流程）
└── tests/
    ├── test_flight_store.py
    ├── test_flight_scan_service.py
    └── test_flight_tracking.py

app/
├── routers/flights.py         # API 驗證：天數區間欄位、組合數上限守衛
└── tests/test_smoke.py        # 既有 trip_days 相關深度比對斷言需同步更新

web/src/pages/
├── FlightTrackForm.jsx        # 建立表單：天數下限／上限兩個輸入框
└── Flights.jsx                # 卡片／結果顯示：呈現天數區間
```

**Structure Decision**：沿用既有 web application 結構（`app/` FastAPI
後端 ＋ `web/` React 前端 ＋ `poc/kb-mcp/` 業務邏輯層），與 005、006
完全一致，不引入新的頂層目錄。id=9 的遷移是**一次性、需要人手動執行**
的獨立腳本，不整合進 `flight_tracking_job.py` 的排程路徑（排程腳本
的職責是「重掃既有條件」，不是「遷移資料模型」，混在一起會讓排程腳本
承擔它不該有的職責，且遷移只需執行一次）。

## Complexity Tracking

*No Constitution violations to justify（無可評估的 gate，見上）。*
