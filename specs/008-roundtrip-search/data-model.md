# Phase 1 Data Model: 單純來回機票搜尋

**Feature**: 008-roundtrip-search
**Date**: 2026-09-24
**Storage**: 沿用既有 `poc/data/flights.db`，**不新增資料庫**，新增
2 張表

## 新增資料表

```text
flights.db（既有）
  flight_track（既有，不變動）
  flight_scan_result（既有，不變動）
  ＋ roundtrip_track（新增）
  ＋ roundtrip_scan_result（新增）
```

### `roundtrip_track`

```sql
CREATE TABLE IF NOT EXISTS roundtrip_track (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    destinations TEXT NOT NULL,        -- 候選目的地清單，逗號分隔（比照
                                        -- 既有 outstations 的儲存慣例）
    hub TEXT NOT NULL DEFAULT 'TPE',
    preferred_transit TEXT,            -- 可選偏好轉機城市，NULL＝交給
                                        -- Google Flights 自動決定
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    trip_days_min INTEGER NOT NULL,
    trip_days_max INTEGER NOT NULL,
    samples_per_month INTEGER NOT NULL DEFAULT 2,
    target_price INTEGER,
    created_at TEXT NOT NULL,
    last_success_at TEXT,
    scan_frequency_days INTEGER NOT NULL DEFAULT 7,
    last_notified_at TEXT,
    last_notified_price INTEGER,
    last_notify_failed INTEGER NOT NULL DEFAULT 0
);
```

與既有 `flight_track` 的差異：沒有 `outstations`／`lead_strategy`／
`trail_strategy`／`exclude_months_lead`／`exclude_months_trail`（單純
來回沒有外站迴圈、沒有第1/4段，這些概念不適用）；`destination`（單數）
換成 `destinations`（複數，候選清單）；新增 `preferred_transit`。天數
欄位從建立就是區間（`trip_days_min`／`trip_days_max`，直接沿用 007
確立的語意，不像四段票有「先有單一值、後來遷移成區間」的歷史包袱）。

`exclude_months_trip`（主行程排除月份）**保留在單純來回的設計意圖
內**，但技術規劃階段評估後決定本次不做：pre-spec 的 speckit-input.md
沒有把它列入單純來回的 In Scope（見 speckit-input.md「In Scope」
清單，只提到候選目的地／天數區間／轉機偏好三項），不擅自擴大範圍；
若之後需要，可用同樣的 `ALTER TABLE ADD COLUMN` 模式安全補上。

### `roundtrip_scan_result`

```sql
CREATE TABLE IF NOT EXISTS roundtrip_scan_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    destination TEXT NOT NULL,         -- 這筆結果對應哪個候選目的地
    outbound_date TEXT NOT NULL,
    return_date TEXT NOT NULL,
    price INTEGER,
    airline TEXT,
    status TEXT NOT NULL,
    queried_at TEXT NOT NULL,
    FOREIGN KEY (track_id) REFERENCES roundtrip_track(id)
);

-- 同一條件下，同一個目的地＋同一組日期只保留一筆（重掃時覆寫）
CREATE UNIQUE INDEX IF NOT EXISTS idx_roundtrip_result_combo
    ON roundtrip_scan_result (track_id, destination, outbound_date,
                              return_date);

CREATE INDEX IF NOT EXISTS idx_roundtrip_result_track
    ON roundtrip_scan_result (track_id);
```

與既有 `flight_scan_result` 的差異：沒有 `outstation`／`leg1_date`／
`leg4_date`／`lead_days`／`trail_days`／`connector_price`（單純來回
只有去程與回程兩個日期，沒有第1/4段的概念，也沒有接駁票——接駁票是
「外站不是目的地本身」這個四段票特有結構才需要的概念，單純來回的
目的地就是實際想去的地方，不需要另外估一段接駁）。新增 `destination`
欄位標示是哪個候選目的地（spec.md FR-05 的資料層基礎）。

## 與既有機制的相容性（逐一對照 research.md 的重用決策）

| 既有函式 | 重用方式 |
|---|---|
| `combination_count()` | 直接呼叫，`num_targets` 傳候選目的地數量 |
| `MAX_COMBINATIONS_PER_TRACK` | 直接沿用同一個常數 |
| `is_due()`／`next_scan_date()` | 直接呼叫，只依賴 `id`／`scan_frequency_days`／`last_success_at`，`roundtrip_track` 都有 |
| `should_notify()`／`should_notify_status()` | 直接呼叫，只依賴傳入的 `lowest_price`／`state`，不關心資料來源 |
| `google_flights_url()` | 直接呼叫，傳 2 段（無轉機偏好）或 4 段（有轉機偏好） |
| `build_notification()`／`build_status_notification()` | **不重用**——訊息內容需要標示候選目的地，四段票版本的訊息格式（四段行程明細）不適用，新增 `build_roundtrip_notification()`／`build_roundtrip_status_notification()` |
| `record_notification()` | 需要 roundtrip 版本（寫入 `roundtrip_track` 而非 `flight_track`），邏輯相同但目標表不同，比照既有方法新增 `record_roundtrip_notification()` |

## 組合數計算公式

```text
組合數 = 月份數（window_start～window_end 展開） × samples_per_month
        × 候選目的地數（len(destinations)） × 天數選項數
         （trip_days_max − trip_days_min + 1）
```

與 007 的四段票公式唯一差異是「外站數」換成「候選目的地數」——
`combination_count()` 的參數本來就是抽象的 `num_targets`，呼叫端
傳什麼數字它不關心，這正是 007 刻意這樣設計的原因（research.md §6）。
