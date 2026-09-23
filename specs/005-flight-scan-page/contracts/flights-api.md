# Interface Contract: 機票分頁 HTTP API

**Feature**: 005-flight-scan-page
**Date**: 2026-09-23
**Scope**: 本專案內部 API（`app/routers/flights.py`），供同源部署的 `web/` 前端使用。
無外部消費者，故不維護版本協商或棄用政策。

## 通用約定

- 路徑前綴：`/api/flights`
- 請求與回應皆為 JSON
- 金額欄位一律為整數新台幣（NTD），不含小數（FR-024）
- 日期為 ISO 8601（`YYYY-MM-DD`），年月為 `YYYY-MM`
- 前端經 `web/src/api/client.js` 呼叫，該 wrapper 已自動帶
  `ngrok-skip-browser-warning` header（既有慣例）

### 錯誤語意（重要）

**配額不足與被外部服務阻擋不是 HTTP 錯誤**，而是正常回應中的狀態值
（spec §API 行為）。它們是預期的營運狀態，不是系統故障。

| HTTP | 使用時機 |
|---|---|
| 200 | 正常回應，含「配額不足」「被阻擋」「掃描中」等營運狀態 |
| 400 | 請求內容不合驗證規則（空外站清單、非正行程天數、月份超出 1–12） |
| 404 | 指定的查詢條件不存在 |
| 500 | 未預期的伺服器錯誤 |

---

## 1. 列出查詢條件

```
GET /api/flights/tracks
```

**回應 200**

```json
{
  "tracks": [
    {
      "id": 1,
      "name": "布拉格（成田／沖繩）",
      "destination": "PRG",
      "hub": "TPE",
      "outstations": ["NRT", "OKA"],
      "window_start": "2027-04",
      "window_end": "2027-06",
      "trip_days": 12,
      "lead_strategy": "m5",
      "trail_strategy": "m3",
      "exclude_months": { "trip": [6,7,8], "lead": [6,7,8], "trail": [6,7,8] },
      "target_price": 38000,
      "samples_per_month": 2,
      "state": "complete",
      "last_success_at": "2026-09-23T09:04:00",
      "progress": { "done": 16, "total": 16 },
      "lowest": {
        "price": 37265,
        "outstation": "NRT",
        "outbound_date": "2027-04-01",
        "return_date": "2027-04-13",
        "target_met": true
      }
    }
  ],
  "quota": {
    "used": 12,
    "limit": 20,
    "window": "rolling_hour",
    "limit_basis": "estimated",
    "seconds_until_free": 0
  }
}
```

**欄位說明**

- `state`：`idle`／`queued`／`scanning`／`partial`／`complete`／`stale`。
  由系統推導（`research.md` §7），非儲存值
- `progress.total`：條件展開的組合總數；`done`：已有結果的組合數
- `lowest`：目前最低價摘要；無任何結果時為 `null`
- `quota.limit_basis`：`measured`／`estimated`。**FR-018 要求介面標明
  限制值的性質**，此欄位讓前端不需硬編文案即可正確呈現

---

## 2. 建立查詢條件

```
POST /api/flights/tracks
```

**請求**

```json
{
  "name": "布拉格（成田／沖繩）",
  "destination": "PRG",
  "hub": "TPE",
  "outstations": ["NRT", "OKA"],
  "window_start": "2027-04",
  "window_end": "2027-06",
  "trip_days": 12,
  "lead_strategy": "m5",
  "trail_strategy": "m3",
  "exclude_months": { "trip": [6,7,8], "lead": [6,7,8], "trail": [6,7,8] },
  "target_price": 38000,
  "samples_per_month": 2
}
```

**回應 201**：`{ "id": 1 }`

建立後**不自動開始掃描**（由端點 4 觸發），使前端可先確認條件正確。

**回應 400**（驗證失敗）

```json
{ "detail": "outstations 不得為空" }
```

驗證項目對應 FR-025：`outstations` 非空、`trip_days` 為正整數、
排除月份每項介於 1–12、`window_end` 不早於 `window_start`。

---

## 3. 刪除查詢條件

```
DELETE /api/flights/tracks/{id}
```

**回應 204**：無內容。連同其掃描結果一併移除（FR-003）。
查價快取為跨條件共用，**不隨之刪除**。

**回應 404**：條件不存在。

---

## 4. 觸發掃描

```
POST /api/flights/tracks/{id}/scan
```

非同步。立即回傳，實際查價於背景進行（FR-011）。

**回應 200（已開始）**

```json
{ "state": "scanning", "planned": 16, "already_cached": 4, "will_query": 12 }
```

**回應 200（配額不足，非錯誤）**

```json
{
  "state": "queued",
  "planned": 16,
  "already_cached": 0,
  "will_query": 0,
  "seconds_until_free": 1680,
  "message": "最近一小時已達查詢上限，約 28 分鐘後釋出名額"
}
```

**回應 200（已在掃描中）**

```json
{ "state": "scanning", "planned": 16, "done": 7 }
```

重複觸發**不建立第二個作業**（Edge Case：同一條件被連續觸發多次），
以既有進度回應。

---

## 5. 查詢結果與進度

```
GET /api/flights/tracks/{id}/results
```

**回應 200**

```json
{
  "state": "partial",
  "progress": { "done": 12, "total": 16 },
  "blocked": false,
  "blocked_kind": null,
  "seconds_until_free": 0,
  "results": [
    {
      "outstation": "NRT",
      "leg1_date": "2026-11-02",
      "outbound_date": "2027-04-01",
      "return_date": "2027-04-13",
      "leg4_date": "2027-04-14",
      "lead_days": 150,
      "trail_days": 1,
      "price": 37265,
      "connector_price": 6800,
      "connector_is_estimate": true,
      "airline": "星宇航空",
      "status": "ok",
      "queried_at": "2026-09-23T09:03:12",
      "links": {
        "four_segment": "https://…",
        "connector": "https://…"
      }
    }
  ],
  "skipped": [
    { "outbound_date": "2027-12-01", "reason": "no_feasible_lead" }
  ]
}
```

**欄位說明**

- `results` 依 `price` 升冪排序，`status` 非 `ok` 者排在最後
- `blocked_kind`：`null`／`soft_timeout`／`explicit`。**區分連續逾時的
  軟阻擋與明確阻擋頁**，兩者對使用者的建議不同（FR-016）
- `connector_is_estimate`：恆為 `true`，讓前端不需硬編「估算」字樣（FR-020）
- `links`：由後端構造，前端不自行拼接查價網址（避免兩處邏輯分岔）
- `skipped`：所有候選間隔都無法避開排除月份而被跳過的日期（FR-010）

---

## 6. 外部原生價格追蹤的說明資料

```
GET /api/flights/native-tracking
```

**回應 200**

```json
{
  "supported_for_four_segment": false,
  "reason": "外部服務的價格追蹤不支援多城市行程；四段票頁面沒有追蹤按鈕（2026-09-23 實測，對照組來回票頁面有）",
  "usable_for": "主行程來回票",
  "steps": ["登入外部服務帳號", "開啟下方主行程來回票連結", "執行提供的腳本或點擊追蹤開關"],
  "main_trip_links": [
    { "label": "台北↔布拉格 2027-04-01～04-13", "url": "https://…" }
  ],
  "script_path": "poc/kb-mcp/scraper/track-prices-console.js"
}
```

滿足 FR-022。`supported_for_four_segment` 為結構化欄位而非純文案，
讓前端能以一致方式呈現這項限制。
