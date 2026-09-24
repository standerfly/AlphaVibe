# Interface Contract: 單純來回機票搜尋 API

**Feature**: 008-roundtrip-search
**Date**: 2026-09-24
**Scope**: 新增端點＋既有清單端點的合併變更。四段票既有端點
（`POST/PATCH/DELETE /api/flights/tracks/{id}`、
`GET /api/flights/tracks/{id}/results`）**不變動**。

## 通用約定

沿用既有約定（`/api/flights` 前綴、JSON、金額為整數 NTD、配額不足與
被阻擋是 200 回應中的狀態值而非 HTTP 錯誤、驗證失敗回 400 並說明
原因）。

## 端點命名：為何是新的獨立路徑而非共用同一組端點

`roundtrip_track` 與 `flight_track` 是各自獨立的 `AUTOINCREMENT`
序列（data-model.md §2），同一個整數 id 可能同時存在於兩張表——不能
只用 `{id}` 判斷要查哪張表。改用路徑區分類型（`/roundtrip/` 字首），
而不是讓呼叫端額外帶一個 `type` 參數去猜對應哪張表。

---

## 1. 建立單純來回條件（新端點）

```
POST /api/flights/tracks/roundtrip
```

**請求**

```json
{
  "destinations": ["AOJ", "CTS", "AXT", "KIJ"],
  "hub": "TPE",
  "preferred_transit": "NRT",
  "window_start": "2027-01",
  "window_end": "2027-02",
  "trip_days_min": 3,
  "trip_days_max": 7,
  "samples_per_month": 2,
  "target_price": 30000,
  "scan_frequency_days": 7,
  "name": null
}
```

- `destinations`：必填，至少 1 個機場代碼（spec.md Edge Cases——不
  強制多個）
- `preferred_transit`：選填，未提供或 `null` 時不限制轉機城市
- `name`：選填，留空時比照既有規則自動產生（目的地清單＋出發區間）
- 其餘欄位驗證規則與既有 `POST /api/flights/tracks` 對應欄位一致

**新增驗證**：組合數超過上限（沿用 `MAX_COMBINATIONS_PER_TRACK`，
候選目的地數取代外站數代入公式）時回 400，錯誤訊息包含算出的組合數
與上限（與 007 的四段票驗證行為一致）。

**回應 201**：`{"id": <int>}`

---

## 2. 列出條件：合併兩種類型（既有端點，回應形狀變更）

```
GET /api/flights/tracks
```

**回應變更**：`tracks` 陣列同時包含四段票與單純來回的條件，每筆
新增 `track_type` 欄位：

```json
{
  "tracks": [
    {"id": 9, "track_type": "four_segment", "destination": "PRG", "...": "..."},
    {"id": 3, "track_type": "roundtrip", "destinations": ["AOJ", "CTS"],
     "preferred_transit": "NRT", "lowest": {
       "price": 46872, "destination": "AOJ",
       "outbound_date": "2027-01-15", "target_met": false,
       "gap_to_target": 16872
     }, "...": "..."}
  ],
  "quota": {"...": "..."}
}
```

單純來回條件的 `lowest` 摘要**新增 `destination` 欄位**——標示這個
最低價是哪個候選目的地（spec.md FR-05）；四段票條件的 `lowest` 不變
（四段票只有單一目的地，不需要這個欄位）。

排序：兩種類型合併後依既有規則排序（沿用清單既有的排序邏輯，不因
類型而分開排序或分組——FR-08 要求同一份清單統一呈現）。

---

## 3. 觸發掃描（新端點）

```
POST /api/flights/tracks/roundtrip/{id}/scan
```

行為與既有 `POST /api/flights/tracks/{id}/scan` 一致（配額不足回
200 排隊，非錯誤；回應含 `planned`／`already_cached`／`will_query`）。

---

## 4. 查詢結果（新端點）

```
GET /api/flights/tracks/roundtrip/{id}/results
```

**回應**：

```json
{
  "state": "complete",
  "progress": {"done": 12, "total": 20},
  "quota": {"...": "..."},
  "blocked": false,
  "blocked_kind": null,
  "results": [
    {"destination": "AOJ", "outbound_date": "2027-01-15",
     "return_date": "2027-01-20", "price": 46872, "airline": "...",
     "status": "ok",
     "links": {"round_trip": "https://www.google.com/travel/flights?..."}}
  ],
  "skipped": [],
  "notify": {"last_notified_at": null, "last_notified_price": null,
             "last_notify_failed": false},
  "next_scan_date": "2027-01-08"
}
```

每筆結果的 `destination` 欄位標示對應的候選目的地（spec.md FR-05）。
`links.round_trip` 由後端用既有 `google_flights_url()` 構造——未指定
`preferred_transit` 時傳 2 段（自動編碼為來回），指定時傳 4 段（自動
編碼為多城市，含轉機）；前端不自行組裝網址（research.md §1，沿用
既有「不在前端重新拼網址」原則）。

不含四段票特有的 `connector_price`／`connector_is_estimate`
（單純來回沒有接駁票概念，data-model.md）。

---

## 5. 刪除條件（新端點）

```
DELETE /api/flights/tracks/roundtrip/{id}
```

行為與既有 `DELETE /api/flights/tracks/{id}` 一致（204，查價快取
跨條件共用不隨之刪除）。

---

## 6. 通知內容（背景排程，非 HTTP 端點）

達標／現況通知訊息明確標示觸發的候選目的地（spec.md FR-10），例如：

```
✈️ 機票降到目標價以下

北海道東北賞雪
目的地：青森（AOJ）
來回票 NT$46,872（目標 NT$30,000）
出發 2027-01-15 ~ 2027-01-20
[Google Flights 連結]
```

與四段票通知的差異：沒有「第1段不可 no-show」的提醒文案（單純來回
沒有第1/4段的風險），改標示目的地名稱。

---

## 7. 不在本次範圍（Deferred）

- `PATCH /api/flights/tracks/roundtrip/{id}`（調整目標價／重掃頻率）：
  speckit-input.md 的 FR-04～11 未要求，本次不做；若後續需要，可比照
  既有 `PATCH /api/flights/tracks/{id}` 的既定模式新增，技術上無阻礙
