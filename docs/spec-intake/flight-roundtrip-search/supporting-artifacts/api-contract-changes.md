# API Contract Changes: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
**Last Updated:** 2026-09-24
**Status:** Draft（product 層級的行為意圖說明，非最終 API 規格——
精確的 request/response schema 留給 Spec Kit `contracts/` 階段設計）

## 為什麼需要這份文件

本次異動修改既有已上線的 `POST /api/flights/tracks`、
`PATCH /api/flights/tracks/{id}`、`GET /api/flights/tracks`、
`GET /api/flights/tracks/{id}/results` 這幾個既有端點的欄位，並可能
新增端點支援單純來回類型。這些端點已被正式服務與前端依賴，變更需要
明確記錄相容性意圖。

## 既有端點的行為變化（意圖層級）

### `POST /api/flights/tracks`（建立追蹤條件）

- 現況：`trip_days`（單一整數，必填）
- 變更：改為天數區間欄位（下限／上限，確切欄位名留給 Spec Kit），
  兩者都必填且上限不得小於下限
- 新增：行程類型欄位（四段票／單純來回），依類型決定其餘欄位是走
  既有四段票欄位組（destination／outstations／lead_strategy／
  trail_strategy）還是單純來回欄位組（候選目的地清單／可選轉機城市
  偏好）
- 新增驗證：算出的查詢組合數超過上限（暫定 60）時回 400 並說明原因
  （沿用既有「驗證失敗必須回 400 並說明原因」慣例，FR-025 精神）

### `PATCH /api/flights/tracks/{id}`（既有：只開放頻率與目標價）

- 天數區間**不**開放 PATCH（沿用既有 `TrackUpdate` 的既定原則：會
  改變枚舉組合的欄位視為「建新條件」而非「編輯」，見 scope-decision
  「Deferred Or Later」）
- 現有的 `scan_frequency_days`／`target_price` PATCH 行為不變

### `GET /api/flights/tracks`（清單）

- 回應中的天數欄位從單一 `trip_days` 改為區間形式
- 新增行程類型欄位，供前端類型切換／篩選使用
- 單純來回類型的條件，`lowest` 摘要需要能標示「哪個候選目的地」
  觸發（clarification-log Q-008）——四段票類型的條件沒有這個欄位
  （因為一個條件只對應一個目的地）

### `GET /api/flights/tracks/{id}/results`（結果）

- 單純來回類型的每筆結果需要標示對應的候選目的地（否則使用者看到
  一堆價格不知道各自是去哪裡）
- 四段票類型的既有欄位（`leg1_date`／`outbound_date`／`return_date`／
  `leg4_date`／`airline` 等）不變

## 通知內容變化

- `build_notification()`／`build_status_notification()`（或其單純
  來回對應版本）在多目的地候選情境下，訊息內容需要明確寫出「這次是
  哪個候選目的地」（clarification-log Q-008），不能只給價格

## 相容性注意事項

- 現有前端（`Flights.jsx`／`FlightTrackForm.jsx`）直接讀 `trip_days`
  單一整數欄位（見 CLAUDE.md／既有程式碼），改成區間形狀是**破壞性
  變更**，前端需要同步更新，不能只改後端
- 現有 smoke test（`app/tests/test_smoke.py`）有針對 `trip_days` 與
  組合數（`progress.total`）的深度比對斷言，schema 變更後這些斷言
  需要同步更新，否則會產生假性失敗或（更危險的）假性通過
