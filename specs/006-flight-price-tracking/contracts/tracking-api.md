# Interface Contract: 價格追蹤的 API 變更

**Feature**: 006-flight-price-tracking
**Date**: 2026-09-23
**Scope**: 對 005 既有端點的**增量變更**，不新增端點。

## 通用約定

沿用 005 的約定（`/api/flights` 前綴、JSON、金額為整數 NTD、
配額不足與被阻擋是 200 回應中的狀態值而非 HTTP 錯誤）。

---

## 1. 建立條件：新增頻率欄位

```
POST /api/flights/tracks
```

**請求新增欄位**

```json
{ "scan_frequency_days": 7 }
```

選填，預設 7。非正整數回 400。

---

## 2. 列出條件：新增排程與通知欄位

```
GET /api/flights/tracks
```

**每個 track 物件新增**

```json
{
  "scan_frequency_days": 7,
  "next_scan_date": "2026-09-30",
  "last_success_at": "2026-09-23T09:04:00",
  "notify": {
    "last_notified_at": "2026-09-23T09:05:12",
    "last_notified_price": 37265,
    "last_notify_failed": false
  }
}
```

- `next_scan_date`：由後端計算（上次成功 ＋ 週期，再對齊到該條件的
  排定星期）。前端不自行推算——那個規則若兩處各寫一份必然分岔。
- `notify.last_notify_failed`：為 true 時介面應標示「通知未送達」（FR-019），
  讓使用者知道要自己回來看。

---

## 3. 更新條件頻率

```
PATCH /api/flights/tracks/{id}
```

**請求**

```json
{ "scan_frequency_days": 14 }
```

**回應 200**：更新後的 track 物件（含重算的 `next_scan_date`）。

**回應 400**：非正整數。
**回應 404**：條件不存在。

這是本功能唯一新增的端點動作。005 沒有更新條件的需求（建立後只能刪除
重建），但 FR-018 要求能調整頻率——為此重建條件會連帶丟掉既有結果。

---

## 4. 掃描結果：不變

```
GET /api/flights/tracks/{id}/results
```

結構與 005 相同。達標與否不在此回報——那屬於條件層級（見端點 2 的
`notify` 區塊），不是單筆結果的性質。
