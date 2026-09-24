# Implementation Plan: 單純來回機票搜尋

**Branch**: `008-roundtrip-search` | **Date**: 2026-09-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-roundtrip-search/spec.md`

## Summary

新增「單純來回」查詢類型：多個候選目的地一起比價、天數區間（沿用
007）、可選偏好轉機城市，整合進同一「機票」分頁並以類型切換呈現。

技術路線：**新增獨立資料表，重用既有查價與排程／通知邏輯**。研究
階段的關鍵發現——`google_flights_url()` 已經會依段數自動判斷
trip type（2 段＝來回、4 段以上＝多城市），單純來回不需要新的網址
組法，只是呼叫端組 2 段或 4 段的差異。資料模型因為欄位重疊度低（四段
票的外站／lead-trail 策略對單純來回沒有意義，單純來回的候選目的地
清單也不是四段票任何欄位能表示），新增 `roundtrip_track`／
`roundtrip_scan_result` 兩張獨立表，但排程（`is_due`／
`next_scan_date`）、通知判定（`should_notify`／`should_notify_status`）、
組合數守衛（`combination_count`／`MAX_COMBINATIONS_PER_TRACK`）這些
007 已經設計成不依賴特定資料形狀的純函式全部直接重用。

## Technical Context

**Language/Version**: Python 3.9.6（硬限制，本機唯一可用版本）
**Primary Dependencies**: 既有 `flight_search.py`（`google_flights_url()`
不需修改）、`flight_scan_service.py`（`combination_count()` 直接重用）、
`flight_store.py`（新增兩張表，既有表不變動）、`flight_tracking_job.py`
（排程迴圈擴充涵蓋新表）、FastAPI／React（既有）。**不新增任何第三方
套件**
**Storage**: 沿用既有 `poc/data/flights.db`，新增
`roundtrip_track`／`roundtrip_scan_result` 兩張表，既有
`flight_track`／`flight_scan_result` 不變動
**Testing**: `unittest`（`poc/kb-mcp/tests/`）＋ `app/tests/test_smoke.py`
**Target Platform**: macOS 本機，`app/` 後端 ＋ `web/` 前端，正式服務
以 `launchd` 常駐（`com.alphavibe.reportserver`）
**Project Type**: Web application（既有）
**Performance Goals**: 與四段票相同——查詢受外部瀏覽器查價速率限制，
非本功能可控制的效能指標
**Constraints**: 查詢仍受既有速率上限約束（約 20 筆／小時，推估值）；
scraper 對「2 段來回」頁面的相容性需要實作階段真實驗證，不能只憑
讀程式碼斷定（research.md §1）
**Scale/Scope**: 單一使用者，全新查詢類型，正式庫目前無既有單純來回
資料需要遷移（與 007 不同，本包不涉及破壞性異動）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**狀態：無可評估的 gate**（與 005、006、007 相同）。

`.specify/memory/constitution.md` 仍是未填寫的樣板（所有原則為
`[PRINCIPLE_N_NAME]` 佔位字串）。本計畫不假裝通過檢核，也不自行擬定
憲章內容——那需要 PO 決策，屬 `/speckit.constitution` 的範圍。

## Project Structure

### Documentation (this feature)

```text
specs/008-roundtrip-search/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   └── roundtrip-api.md
└── tasks.md              # Phase 2 output (/speckit.tasks，本指令不建立)
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── flight_store.py            # 新增 roundtrip_track／roundtrip_scan_result
│                               # 兩張表與對應 CRUD 方法；既有四段票表不變動
├── flight_scan_service.py     # 新增 roundtrip 版本的 expand（多目的地展開）、
│                               # 重用 combination_count()／is_due()／
│                               # next_scan_date()／should_notify()／
│                               # should_notify_status()
├── flight_search.py           # 不變動（google_flights_url() 已支援兩種
│                               # trip type，research.md §1）
├── flight_tracking_job.py     # 排程迴圈擴充：同時對 flight_track 與
│                               # roundtrip_track 兩張表跑 due_tracks()
└── tests/
    ├── test_flight_store.py（新增 roundtrip 相關測試類別）
    ├── test_flight_scan_service.py（新增 roundtrip 展開／通知測試）
    └── test_flight_tracking.py（排程涵蓋兩張表的測試）

app/
├── routers/flights.py         # GET /api/flights/tracks 合併兩張表；
│                               # 新增單純來回的建立／結果端點
└── tests/test_smoke.py        # 新增單純來回的深度比對斷言

web/src/pages/
├── Flights.jsx                # 類型切換 UI；卡片依 track_type 呈現
│                               # 不同內容
└── FlightTrackForm.jsx        # 新增單純來回的建立表單（候選目的地
                                # 多選、可選轉機城市）
```

**Structure Decision**：沿用既有 web application 結構，與 005、006、
007 完全一致，不引入新的頂層目錄。新資料表與既有四段票表落在同一個
`flights.db`（沿用「一個領域一個獨立 db」慣例，不需要再拆一層）。

## Complexity Tracking

*No Constitution violations to justify（無可評估的 gate，見上）。*
