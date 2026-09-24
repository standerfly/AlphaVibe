# Phase 0 Research: 單純來回機票搜尋

**Feature**: 008-roundtrip-search
**Date**: 2026-09-24

007 已解決「天數區間怎麼展開、組合數怎麼守衛」。本階段解決 pre-spec
明確標注「留給 Spec Kit」的三個技術問題：資料模型要不要跟四段票共用、
轉機偏好怎麼影響查詢網址、通知怎麼跨多目的地判定最低價。

---

## §1 查詢網址構造：`google_flights_url()` 不需要任何改動

**Decision**：單純來回沿用既有 `google_flights_url(legs)` 不改一行——
未指定轉機偏好時傳 2 段（TPE→目的地、目的地→TPE），指定轉機偏好時傳
4 段（TPE→轉機、轉機→目的地、目的地→轉機、轉機→TPE）。

**Rationale**：讀了 `flight_search.py` 的既有實作才發現這行既有邏輯：

```python
trip = 2 if len(legs) == 1 else (1 if len(legs) == 2 else 3)
```

trip type 完全由 `legs` 的段數自動決定——**2 段自動編碼成
「來回」（trip=1），不是多城市**。這代表：

- 未指定轉機偏好：傳 2 段，`google_flights_url()` 自動產出真正的來回
  網址（trip=1），不是硬湊出來的兩段 multi-city
- 指定轉機偏好：傳 4 段（含轉機的去程兩段＋回程兩段），落入既有的
  「3 段以上＝多城市」（trip=3）分支——這條路徑四段票功能已完整驗證
  過（真實查價、真實封鎖測試皆通過）

兩種情境**都不需要新增或修改 `google_flights_url()` 本身**，只是呼叫端
（單純來回的展開邏輯）決定要組 2 段還是 4 段的 `legs` 清單。這比
pre-spec 階段（`docs/spec-intake/flight-roundtrip-search/`）評估的
「需要兩條技術路徑」更簡單——兩條路徑其實是同一支函式的兩種呼叫方式。

**Alternatives considered**：
- 另外寫一支 `google_flights_roundtrip_url()`：**被否決**。既有函式已
  经透過段數自動判斷 trip type，另寫一份只是重複邏輯、製造兩處网址
  組法分岔的風險（跟既有「不要在前端重新拼網址」的既定原則同理）。

**尚待驗證（不是本階段就能確認）**：scraper（`flight_scraper.js`）
對「2 段來回」頁面的相容性——`isMultiCity = body.includes('整趟行程')`
這個既有判斷邏輯，對純來回頁面應該會落入「非多城市」分支（用
`/\$[0-9][0-9,]{3,}/` 正則抓價格），跟 `estimate_connectors_browser()`
的單程接駁票路徑用的是同一套判斷。但**這是推論，不是已驗證的事實**
——來回搜尋結果頁的實際 DOM 結構有沒有踩到既有正則的邊界情況（例如
頁面文字裡剛好也含「整趟行程」字樣、或票價欄位格式不同），要留到
實作階段用真實瀏覽器查價驗證，不能只憑讀程式碼就斷定沒問題。

---

## §2 資料模型：獨立資料表，不與四段票共用

**Decision**：新增 `roundtrip_track`／`roundtrip_scan_result` 兩張獨立
資料表（同樣落在既有 `flights.db`，不新建資料庫），不擴充既有
`flight_track`／`flight_scan_result` 加類型欄位。

**Rationale**：比對兩種類型實際需要的欄位，重疊部分與差異部分都很
明顯：

| 欄位 | 四段票需要 | 單純來回需要 |
|---|---|---|
| 目的地 | 單一 `destination` | 多個候選目的地（清單） |
| 外站 | `outstations`（迴圈概念） | 不需要 |
| hub | 需要（外站經由 hub 轉機到目的地） | 只在指定轉機偏好時才需要 |
| lead/trail 策略 | 需要（第1段提前／第4段延後） | 不需要（沒有第1/4段） |
| 排除月份（lead/trail） | 需要 | 不需要 |
| 偏好轉機城市 | 不需要（用 hub 概念） | 需要（新欄位） |
| 天數區間、目標價、重掃頻率、通知欄位 | 需要 | 需要（跟四段票共用語意） |

四段票專屬欄位（外站、lead/trail 策略）對單純來回完全沒有意義；單純
來回需要的「多個候選目的地」也不是四段票的任何既有欄位能表示的
（`outstations` 語意是「同一個目的地、不同起訖外站」，候選目的地的
語意是「互相比較的不同目的地」，兩者不能共用同一個欄位）。硬塞進
同一張表會產生大量依類型而定的 NULL 欄位，且每個讀寫方法都要先判斷
類型分支，比兩張各自乾淨的表更難維護。

結果列也是同理：四段票結果需要 `leg1_date`／`leg4_date`／
`lead_days`／`trail_days`／`connector_price`（接駁票概念）；單純
來回結果只需要 `destination`（是哪個候選目的地）／`outbound_date`／
`return_date`，完全沒有第1/4段與接駁票的概念。

**Alternatives considered**：
- `flight_track` 加 `track_type` 欄位＋一堆 nullable 的類型專屬欄位：
  **被否決**。上表列出的欄位重疊度低，共用表只會讓表變成「稀疏
  聯集」，且既有的 `create_track()`／`_row_to_track()` 等方法要嘛
  變得到處是 `if track_type == ...`，要嘛被迫用同一組參數名硬套
  兩種不同語意（例如 `destination` 到底是單一目的地還是候選清單）。
- 完全獨立的新資料庫檔案：**被否決**。單純來回仍屬於「機票」這個
  領域，跟四段票共用 `flights.db` 比照既有「每個領域一個獨立 db」
  的慣例（`us_stocks.db`／`photos.db`），不需要再拆一層。

---

## §3 排程如何同時涵蓋兩張表

**Decision**：`flight_tracking_job.py` 的每日排程改為分別對
`flight_track` 與 `roundtrip_track` 各自呼叫 `due_tracks()`／
`is_due()`／`next_scan_date()`——這三個函式的既有簽章只依賴
`id`／`scan_frequency_days`／`last_success_at` 三個欄位，兩張表都有
這三個欄位，**函式本身不需要修改**，只是呼叫端要對兩張表各自呼叫
一次再合併今天到期的清單。

**Rationale**：`is_due()`／`next_scan_date()` 已經是不依賴四段票
專屬欄位的邏輯（只看 `id % 7` 與週期），本來就可以直接套用到任何
「有 id、有 scan_frequency_days、有 last_success_at」的資料列，不需要
為單純來回另外設計排程演算法。

**Alternatives considered**：
- 把兩張表的排程欄位抽成第三張共用表：**被否決**，過度設計——現有
  函式已經是純函式風格，不需要額外的正規化表來達到重用。

---

## §4 通知：跨候選目的地判定最低價

**Decision**：新增 `roundtrip_lowest_result(track_id)`（`FlightStore`
的單純來回對應方法），從 `roundtrip_scan_result` 撈出該條件**所有
候選目的地中**價格最低的一筆（`status='ok' ORDER BY price ASC
LIMIT 1`，跟既有 `lowest_result()` 邏輯一致，只是資料表不同）。
`should_notify()`／`should_notify_status()` 本身不需要修改——這兩個
函式的既有簽章是 `(track, lowest_price, state)`，不關心 `lowest_price`
是怎麼算出來的，只要呼叫端傳入「跨候選目的地最低價」即可正確運作。

新增 `build_roundtrip_notification()`／
`build_roundtrip_status_notification()`（既有 `build_notification()`／
`build_status_notification()` 的單純來回版本）——訊息內容需要明確
寫出「是哪個候選目的地」（spec.md FR-10），既有版本的訊息格式（四段
行程明細）對單純來回不適用，不能直接重用，但共用同一個
`_notification_trip_lines()`-style 的抽取模式（避免兩份訊息各自
硬編碼日期/連結組裝邏輯）。

**Rationale**：`should_notify()`／`should_notify_status()` 的判定邏輯
（達標／比上次更低／stale 時不通知）完全是通用的價格比較邏輯，不
關心背後是四段票還是單純來回、也不關心「最低價」是從哪張表算出來
的——這是既有設計已經做對的抽象層級，不需要改。真正需要新增的只有
「怎麼從單純來回的資料撈出最低價」與「通知內容怎麼呈現」。

**Alternatives considered**：
- 讓 `should_notify()` 直接接受 track_id 自己去查資料庫：**被否決**。
  現有設計刻意讓判定函式是純函式（不碰資料庫），方便測試也方便
  未來重用，改成內部查資料庫是不必要的耦合。

---

## §5 API 層：同一份清單如何合併兩種類型

**Decision**：`GET /api/flights/tracks` 改為分別查詢
`store.list_tracks()`（四段票）與 `store.list_roundtrip_tracks()`
（單純來回，新方法），各自組出摘要後合併成一份清單回傳，每筆摘要
新增一個 `track_type` 欄位（`"four_segment"`／`"roundtrip"`）供前端
判斷要用哪種卡片內容渲染。

**Rationale**：FR-08 要求同一分頁呈現，但底層是兩張結構不同的表
（§2），API 層是自然該做「合併呈現」這件事的地方——後端組好統一
形狀的摘要，前端不需要知道底層是幾張表。

**Alternatives considered**：
- 前端分別打兩個端點、自己合併排序：**被否決**。排序（例如依
  `next_scan_date` 或建立時間排序）邏輯若交給前端，日後排序規則
  改變需要同步改前後端兩處；後端合併好一次到位。

---

## §6 組合數上限守衛延伸到候選目的地維度

**Decision**：`combination_count()`（007 已完成的純函式）直接重用，
呼叫時把 `num_targets` 參數傳入候選目的地數量（原本四段票傳外站
數量）；`MAX_COMBINATIONS_PER_TRACK` 沿用同一個常數，不為單純來回
另設門檻（pre-spec Assumption，PO 未表示需要不同上限）。

**Rationale**：007 的 `research.md §4` 設計 `combination_count()` 時
就已經刻意讓它不依賴 `Track` 物件形狀、只吃抽象計數參數，正是為了
讓本包能直接重用——這裡不需要任何新設計，只是兌現當初的設計意圖。
