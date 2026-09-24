# Phase 1 Data Model: 四段票天數區間化

**Feature**: 007-trip-day-range
**Date**: 2026-09-24
**Storage**: 沿用既有 `poc/data/flights.db`，**不新增資料庫**

## 變更範圍

只在既有 `flight_track` 表新增 2 個欄位，並遷移唯一一筆既有記錄
（id=9）。**不新增任何資料表**。

```text
flight_track（既有）
  ＋ trip_days_min      行程天數下限
  ＋ trip_days_max      行程天數上限
  （trip_days 舊欄位保留在 schema，應用程式碼停止讀取，見 research.md §2）
```

---

## 新增欄位

| 欄位 | 型別 | 說明 | 驗證規則 |
|---|---|---|---|
| `trip_days_min` | INTEGER | 行程天數下限 | 正整數（>0） |
| `trip_days_max` | INTEGER | 行程天數上限 | 正整數（>0）且不得小於 `trip_days_min` |

### 為何下限等於上限時要能正常運作（等同舊版單一天數）

`trip_days_min == trip_days_max` 是合法輸入（見 spec.md Edge Cases），
對應「只查一種天數」——這其實就是舊版固定天數的語意，天數選項數展開
後只有 1 個值，行為上完全等價。不需要為這個情況寫特殊分支，展開邏輯
（research.md §1 的外層迴圈）本來就處理得了「迴圈只跑一次」的情況。

### 為何不用單一「彈性天數清單」欄位（例如逗號分隔的 `10,11,12,13,14`）

- 區間比清單更貼近使用者心智模型（PO 說的是「10～14 天」不是列舉
  5 個數字）
- 區間的驗證規則簡單（下限≤上限），清單則要驗證每個元素、去重、
  排序，複雜度不成比例
- 前端輸入體驗上，兩個數字輸入框比一個「輸入清單」的欄位更直覺

---

## 既有欄位語意變化

| 欄位 | 變化前 | 變化後 |
|---|---|---|
| `trip_days` | 唯一的天數來源，`NOT NULL`，應用程式碼直接讀寫 | **停止讀取**；新建列時仍寫入（鏡射 `trip_days_max`）僅為滿足既有 `NOT NULL` 約束，不作為任何邏輯的輸入來源 |

---

## 組合數計算公式（本次新增的驗證概念，非資料表欄位）

```text
組合數 = 月份數（window_start～window_end 展開） × samples_per_month
        × 外站數（len(outstations)） × 天數選項數（trip_days_max − trip_days_min + 1）
```

此公式只在**建立條件時**用來驗證是否超過上限（預設 60，見
`flight_scan_service.py` 新增的純函式，research.md §4），不持久化
成資料表欄位——它是既有欄位的推導值，存第二份等於製造另一個可能
不同步的真相來源。

## id=9 遷移後的資料狀態

| 欄位 | 遷移前 | 遷移後 |
|---|---|---|
| `trip_days`（舊欄位） | 12 | 14（鏡射 `trip_days_max`，不再被讀取） |
| `trip_days_min`（新） | NULL | 10 |
| `trip_days_max`（新） | NULL | 14 |
| `target_price` | 40000 | 40000（不變） |
| `scan_frequency_days` | 7 | 7（不變） |
| `last_notified_at`／`last_notified_price`／`last_notify_failed` | 既有值 | 不變 |
| `last_success_at` | 既有值 | 遷移腳本本身不觸發查價，維持遷移前的值，直到下次（手動或排程）掃描成功才更新 |

遷移不清除既有的 `flight_scan_result` 列（舊的 12 天查價結果）——
它們對應的組合在新的 10～14 天展開下多數不會再被引用（除非 12 天
剛好落在新區間內，此時該筆舊結果可能被新一輪掃描覆寫或保留，取決於
是否命中快取，不特別處理）。
