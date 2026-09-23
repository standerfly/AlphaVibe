# Implementation Plan: 機票價格追蹤與通知

**Branch**: `006-flight-price-tracking` | **Date**: 2026-09-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/006-flight-price-tracking/spec.md`

## Summary

讓 005 建立的查詢條件能**自動重掃**並在**跌破目標價時主動通知**，
同時避免以過期資料發出誤導的通知。

技術路線：**不重新實作任何掃描邏輯**。005 已完成的
`flight_scan_service.run_scan()` 含配額裁切、逐筆落地、軟阻擋即停等行為，
本功能只是在它外面加一層「什麼時候跑」與「跑完要不要通知」。新增的程式
集中在三處：排程腳本、通知判定、以及資料表的幾個欄位。

## Technical Context

**Language/Version**: Python 3.9.6（硬限制，本機唯一可用版本）
**Primary Dependencies**: 既有 `flight_scan_service.py`（005，178 測試）、
既有 `notify.py`（2026-09-17 架構體檢 B4 建立的共用通知模組）、
FastAPI／React（既有）。**不新增任何第三方套件**
**Storage**: 沿用 `poc/data/flights.db`，在既有 `flight_track` 表新增欄位
**Testing**: `unittest`（`poc/kb-mcp/tests/`）＋ `app/tests/test_smoke.py`
**Target Platform**: macOS 本機，排程以 `launchd` 執行獨立腳本
**Project Type**: Web application（`app/` 後端 ＋ `web/` 前端）＋ 排程腳本
**Performance Goals**: 排程腳本單次執行不超過既有掃描的耗時；通知為單次
HTTP 請求
**Constraints**: 排程**不得依賴網頁服務在跑**（FR-016）；通知失敗不得
影響掃描（FR-011）；外部查價速率上限使高頻重掃不可行
**Scale/Scope**: 單一使用者，1–5 個追蹤條件，每週各重掃一次

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**狀態：無可評估的 gate**（與 005 相同）。

`.specify/memory/constitution.md` 仍是未填寫的樣板（所有原則為
`[PRINCIPLE_N_NAME]` 佔位字串）。本計畫不假裝通過檢核，也不自行擬定憲章
內容——那需要 PO 決策，屬 `/speckit.constitution` 的範圍。

替代的品質約束來自 `CLAUDE.md`（Python 3.9 相容、僅標準庫、獨立 store、
不重寫既有演算法）與 pre-spec 基線的 14 項約束。

## Project Structure

### Documentation (this feature)

```text
specs/006-flight-price-tracking/
├── plan.md               # 本檔
├── research.md           # Phase 0 輸出
├── data-model.md         # Phase 1 輸出
├── quickstart.md         # Phase 1 輸出
├── contracts/
│   └── tracking-api.md   # Phase 1 輸出
├── checklists/
│   └── requirements.md   # 已完成，16 項全過
└── tasks.md              # Phase 2（由 /speckit.tasks 產生）
```

### Source Code (repository root)

```text
poc/kb-mcp/
├── flight_store.py             # 既有：新增頻率／排程／通知追蹤欄位
├── flight_scan_service.py      # 既有：新增達標判定與通知決策（不改掃描邏輯）
├── flight_tracking_job.py      # 新增：排程進入點（launchd 呼叫的獨立腳本）
├── notify.py                   # 既有共用通知模組，直接複用不修改
└── tests/
    ├── test_flight_tracking.py # 新增：排程選取、達標判定、去重、過期防護
    └── test_flight_store.py    # 既有：補新欄位的測試

app/routers/flights.py          # 既有：條件回應加入排程與通知欄位
web/src/pages/
├── Flights.jsx                 # 既有：顯示下次重掃、上次成功、通知狀態
└── FlightTrackForm.jsx         # 既有：新增重掃頻率選項

~/Library/LaunchAgents/
└── com.alphavibe.flighttracking.plist   # 新增：每日觸發排程腳本
```

**Structure Decision**: 沿用 005 已建立的三層分工，不新增架構層次。
唯一的新檔案是排程腳本 `flight_tracking_job.py`——它是 `launchd` 的進入點，
必須能獨立於網頁服務執行（FR-016），因此不能放在 `app/` 底下。
這與 `market_scan.py`、`us_stock_scan.py` 等既有排程腳本的位置一致。

## Complexity Tracking

> 憲章未建立，故無「違反憲章」可言。此處記錄本計畫刻意接受的一項複雜度。

| 複雜度 | 為何需要 | 被否決的簡單選項與原因 |
|--------|----------|----------------------|
| 排程腳本每日執行、自行判斷「今天輪到誰」，而非為每個條件各建一個 launchd job | 條件是使用者動態建立的，若每個條件一個 plist，新增／刪除條件就得動系統設定，且 plist 無法由網頁服務安全地增刪 | 每條件一個 plist：需要網頁服務有寫入 `~/Library/LaunchAgents/` 與呼叫 `launchctl` 的能力，那是遠大於本功能所需的權限，且刪除條件時容易留下孤兒 plist |
