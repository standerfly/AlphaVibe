# Phase 1 Data Model: 機票掃描分頁

**Feature**: 005-flight-scan-page
**Date**: 2026-09-23
**Storage**: SQLite，獨立資料庫 `poc/data/flights.db`（比照 `us_stocks.db`／`photos.db`）

## 概覽

兩張新表。查價快取與配額紀錄**刻意不進 DB**——兩者已由
`flight_search.py` 以檔案形式管理（`poc/data/flight_cache/`、
`poc/data/flight_browser_usage.json`）並經測試覆蓋，遷移只增加風險
（見 `research.md` §1、§6）。

```text
flight_track (查詢條件)
    │ 1
    │
    │ N
flight_scan_result (掃描結果)
```

---

## Entity: flight_track（查詢條件）

使用者定義的一組搜尋參數，可長期保存與重複掃描。

| 欄位 | 型別 | 說明 | 驗證規則 |
|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | — | — |
| `name` | TEXT | 顯示名稱；未填時由目的地與區間自動生成 | 非空白 |
| `destination` | TEXT | 目的地機場代碼 | 3 個英文字母，存為大寫（FR-001） |
| `hub` | TEXT | 轉機樞紐機場代碼 | 3 個英文字母；預設為使用者所在地機場 |
| `outstations` | TEXT | 候選外站，以逗號分隔的機場代碼 | **不得為空**（FR-025）；每項 3 個英文字母 |
| `window_start` | TEXT | 出發區間起（`YYYY-MM`） | 合法年月 |
| `window_end` | TEXT | 出發區間訖（`YYYY-MM`） | 合法年月，且不早於 `window_start` |
| `trip_days` | INTEGER | 主行程天數 | **正整數**（FR-025） |
| `lead_strategy` | TEXT | 第1段間隔策略 | 枚舉：`none`／`m1`／`m3`／`m5`／`auto`（FR-006） |
| `trail_strategy` | TEXT | 第4段間隔策略 | 同上（FR-006） |
| `exclude_months_trip` | TEXT | 主行程排除月份，逗號分隔 | 每項介於 1–12（FR-009、FR-025）；可為空 |
| `exclude_months_lead` | TEXT | 第1段排除月份 | 同上 |
| `exclude_months_trail` | TEXT | 第4段排除月份 | 同上 |
| `target_price` | INTEGER | 目標價（NTD） | 非負；**本 feature 僅儲存不觸發通知**（見 spec Assumptions） |
| `samples_per_month` | INTEGER | 每月抽樣日期數 | 正整數；預設 2 |
| `created_at` | TEXT | 建立時間（ISO 8601） | — |
| `last_success_at` | TEXT NULL | 上次成功完成掃描的時間 | 唯一需要儲存的狀態類欄位，見下方「狀態」一節 |

### 為何三組排除月份而非一組

FR-009 要求主行程、第1段、第4段**各自獨立**設定。實務理由：使用者可能
願意在旺季飛主行程（假期受限），但不希望額外的外站旅行也撞旺季。
三組分開儲存，不共用一個欄位。

---

## Entity: flight_scan_result（掃描結果）

一個查詢條件下的一筆具體組合報價。每次重掃覆蓋同一組合的舊值。

| 欄位 | 型別 | 說明 | 驗證規則 |
|---|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | — | — |
| `track_id` | INTEGER FK → flight_track.id | 所屬條件；條件刪除時一併移除（FR-003） | 必須存在 |
| `outstation` | TEXT | 外站機場代碼 | 3 個英文字母 |
| `leg1_date` | TEXT | 第1段日期（外站→樞紐） | ISO 日期；不得早於今日 |
| `outbound_date` | TEXT | 第2段日期（樞紐→目的地，主行程去程） | ISO 日期 |
| `return_date` | TEXT | 第3段日期（目的地→樞紐，主行程回程） | ISO 日期，不早於 `outbound_date` |
| `leg4_date` | TEXT | 第4段日期（樞紐→外站） | ISO 日期，不早於 `return_date` |
| `lead_days` | INTEGER | 第1段與第2段的間隔天數 | ≥ 0 |
| `trail_days` | INTEGER | 第3段與第4段的間隔天數 | ≥ 0 |
| `price` | INTEGER NULL | 四段票價（NTD） | 成功時為正整數；其他狀態為 NULL |
| `connector_price` | INTEGER NULL | 接駁票估價（NTD），標示為估算值（FR-020） | 正整數或 NULL |
| `airline` | TEXT NULL | 航空公司 | — |
| `status` | TEXT | 結果狀態 | 枚舉：`ok`／`no_fare`／`failed`（FR-023 要求區分後兩者） |
| `queried_at` | TEXT | 查詢時間（ISO 8601） | — |

### 唯一性

同一 `track_id` 下，`(outstation, leg1_date, outbound_date, return_date, leg4_date)`
唯一。重掃時以此為鍵覆寫，避免同組合累積多筆。

### 為何存四段各自的日期而非只存偏移量

偏移量可由日期算回，但反之不然——`lead_strategy` 為 `auto` 時，每個主行程
日期的間隔可能不同（FR-007），只存策略無法還原實際航段日期。而外部查價
連結（FR-019）需要四段的確切日期才能構造。

---

## 狀態：推導為主，儲存為輔

`supporting-artifacts/workflow-and-states.md` 定義七個狀態。本模型**只儲存
一個時間戳**，其餘即時推導（`research.md` §7）：

| 狀態 | 判定方式 |
|---|---|
| Idle | 無未完成組合、無進行中的背景任務 |
| Queued | 有未完成組合，但本時段剩餘配額為 0 |
| Scanning | 有進行中的背景任務 |
| Partial | 有未完成組合、無進行中任務、且已有部分結果 |
| Complete | 無未完成組合 |
| TargetMet | Complete 且最低 `price` ≤ `target_price`（本 feature 僅顯示，不通知） |
| **Stale** | **需儲存**：`last_success_at` 距今超過 2 個重掃週期 |

「未完成組合」＝ 條件展開的組合清單 − 已在查價快取中的組合。
枚舉是純函式，相同條件必得相同結果，故推導是確定的。

---

## 與既有資料的關係

| 既有資料 | 位置 | 本 feature 的用法 |
|---|---|---|
| 查價快取 | `poc/data/flight_cache/*.json`（檔案式） | **唯讀依賴**：用於判斷組合是否已查過。不修改其格式 |
| 配額使用紀錄 | `poc/data/flight_browser_usage.json` | **唯讀依賴**：用於顯示剩餘配額與預估等待時間 |
| 投資／相簿資料 | `alphavibe.db`／`us_stocks.db`／`photos.db` | **完全無關**，不跨庫查詢 |

## 遷移

新資料庫、新表，無既有資料需遷移。`FlightStore.__init__()` 建表時
**不得有任何寫入副作用**——`kb_store.py` 曾因在建構子內自動寫入種子資料
而污染正式資料庫兩次（2026-08-22 教訓，見 `CLAUDE.md`）。
