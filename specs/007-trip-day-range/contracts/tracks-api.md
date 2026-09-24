# Interface Contract: 四段票天數區間化的 API 變更

**Feature**: 007-trip-day-range
**Date**: 2026-09-24
**Scope**: 對既有 005／006 端點的**增量變更**，不新增端點。

## 通用約定

沿用既有約定（`/api/flights` 前綴、JSON、金額為整數 NTD、配額不足與
被阻擋是 200 回應中的狀態值而非 HTTP 錯誤、驗證失敗回 400 並說明
原因）。

---

## 1. 建立條件：天數欄位改為區間，新增組合數上限驗證

```
POST /api/flights/tracks
```

**請求欄位變化**

- 移除：`trip_days`（單一整數）
- 新增：`trip_days_min`（必填，正整數）、`trip_days_max`（必填，正整數，
  不得小於 `trip_days_min`）

```json
{
  "trip_days_min": 10,
  "trip_days_max": 14
}
```

**新增驗證**：展開後的查詢組合數（見 data-model.md 公式）超過上限
（預設 60）時，回 400，錯誤訊息包含算出的組合數與上限，例如：

```json
{ "detail": "查詢組合數 120 超過上限 60，請縮小天數區間或外站數量" }
```

---

## 2. 列出條件／取得結果：天數欄位形狀變化

```
GET /api/flights/tracks
GET /api/flights/tracks/{id}/results
```

**每個 track 物件的天數欄位變化**

```json
{
  "trip_days_min": 10,
  "trip_days_max": 14
}
```

（不再回傳單一的 `trip_days` 欄位）

---

## 3. PATCH 端點：天數區間不開放編輯

```
PATCH /api/flights/tracks/{id}
```

**不變**——沿用既有只開放 `scan_frequency_days`／`target_price` 的
行為（FR-007）。`trip_days_min`／`trip_days_max` 不加入可編輯欄位；
若請求中帶了這兩個欄位，直接忽略（不報錯，比照現有其他未知欄位的
容忍行為，避免前端舊版本殘留欄位造成非預期的 400）。

---

## 4. 相容性影響

- **前端 `FlightTrackForm.jsx`**：建立表單的單一「行程天數」輸入框
  改為兩個輸入框（下限／上限）
- **前端 `Flights.jsx`**：卡片與結果列表呈現天數欄位的地方（原本顯示
  單一數字）改為顯示區間（例如「10～14 天」）
- **既有 smoke test（`app/tests/test_smoke.py`）**：依賴 `trip_days`
  單一整數與 `progress.total` 組合數的深度比對斷言，需同步更新為
  依賴 `trip_days_min`／`trip_days_max` 與新的組合數公式
