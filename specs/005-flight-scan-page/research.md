# Phase 0 Research: 機票掃描分頁

**Feature**: 005-flight-scan-page
**Date**: 2026-09-23

本階段不研究「外站四段票怎麼查」——那已在
`docs/research/2026-09-22-ex-station-4segment-ticket-search.md`（943 行）
完成並實測，且成果已實作為 `poc/kb-mcp/flight_search.py`（112 測試）。
本文件只解決**把既有能力接上網頁分頁**所需的實作決策。

---

## §1 資料層放置與隔離

**Decision**：新增 `poc/kb-mcp/flight_store.py`，使用獨立資料庫
`poc/data/flights.db`。經 `app/flight_deps.py` 注入 router。

**Rationale**：`us_stock_store.py`（`us_stocks.db`）與 `photo_store.py`
（`photos.db`）已建立此慣例，且 `CLAUDE.md` 記載美股採獨立 db 是
「產品硬性要求，非技術偏好」。機票與投資資料同樣無任何關聯查詢需求。

**Alternatives considered**：
- 併入 `kb_store.py`（`alphavibe.db`）：被否決。會讓不相關的領域共用
  schema 與遷移路徑，且違反既有兩個 feature 建立的先例。
- 查價快取也遷入 DB：被否決。既有 `poc/data/flight_cache/` 檔案式快取
  已在真實查價中運作（44 筆），且「以行程組合 hash 為鍵」的存取模式
  用檔案系統已足夠；遷移只增加風險而無實益。

---

## §2 掃描進度如何持久化（本階段最關鍵的決策）

**Decision**：**不儲存進度**。進度由「條件展開的組合清單」與「既有查價
快取」兩者相減推導而得：未完成 ＝ 枚舉出的組合 − 已在快取中的組合。

**Rationale**：
1. FR-015 要求逐筆保存、FR-014 要求不重複查價、US3 情境 4 要求
   **服務重啟後只查未完成者**。既有的查價快取本身就是逐筆落地的，
   因此「哪些已完成」這個事實已經被持久化了——再存一份進度就是同一事實
   的第二份來源，兩者不同步時無從判斷誰對。
2. 枚舉是純函式（`build_itineraries_fixed_trip()` 等已存在且經測試），
   給定相同條件必得相同組合，所以相減結果是確定的。
3. 跨時段續掃因此自然成立：第二批只會拿到還沒進快取的組合。

**Alternatives considered**：
- 比照 `photos.py` 用模組內記憶體字典：**被否決**。該檔案 docstring 已
  自述「只有伺服器 process 真的重啟才會遺失，這是 MVP 階段的合理簡化」。
  相簿匯入是單次數分鐘的作業，該簡化可接受；本功能的掃描會跨數小時與
  服務重啟（速率上限所致），同樣的簡化會直接違反 US3 情境 4。
- 新增 `scan_progress` 資料表：被否決。同一事實兩份來源的不同步風險，
  換來的只是省下一次枚舉（純記憶體運算，成本可忽略）。

---

## §3 背景執行機制與一個已知陷阱

**Decision**：使用 FastAPI `BackgroundTasks`。背景任務**不使用**
request-scoped 的 `Depends(get_flight_store)`，改比照
`app/photo_deps.py::resolve_photo_data_dir_for_background()` 新增
`resolve_flight_data_dir_for_background()`，由背景任務自行建立與關閉
獨立的 `FlightStore` 連線。

**Rationale**：`app/routers/photos.py` 的 docstring 明確記載此陷阱——
request-scoped 依賴的連線「在 response 送出後可能已經被 `finally` 關閉」，
背景任務再去用就會操作到已關閉的連線。這是既有 feature 踩過並記錄的坑，
直接沿用其解法。

**Alternatives considered**：
- 獨立常駐 worker process：被否決。單人系統、每次掃描數十筆，引入
  process 管理與 IPC 的複雜度不合比例。
- 完全交給 `launchd` 排程腳本：被否決。本 feature 需要**使用者手動觸發**
  （FR-011、US1 情境 2），排程無法滿足即時觸發。定期重掃屬
  `flight-price-tracking`（handoff order 2），那裡才會用 `launchd`。

---

## §4 SQLite 連線與併發

**Decision**：`sqlite3.connect(path, check_same_thread=False)`。
`app/tests/test_smoke.py` 必須包含機票路由的**併發請求**測試。

**Rationale**：`kb_store.py:372` 與 `us_stock_store.py:133` 皆有此設定並
附註為 2026-08-22 的教訓。`CLAUDE.md` 記載該次事故的完整經過：FastAPI 的
sync generator dependency 由 anyio thread pool 執行，同一 request 的建立與
關閉不保證在同一條 worker thread，正式環境 30 個併發請求有 23 個 500。
同一份教訓也指出：當時的深度測試全部使用「依序單一請求」，完全沒測到
只有併發才會踩到的 race，是上線後由使用者發現的。

**Alternatives considered**：
- 每次請求開新連線不共用：被否決。與既有兩個 store 的結構不一致，
  且既有解法已在正式環境驗證（30/30 通過）。

---

## §5 前端進度更新方式

**Decision**：輪詢。掃描進行中時以固定間隔向進度端點取值，完成後停止。

**Rationale**：`web/src/pages/Gateway.jsx:115` 已有
`setInterval(refreshAll, POLL_INTERVAL_MS)` 的先例，模式與依賴皆已存在。
掃描以分鐘為單位推進，秒級輪詢已足夠即時。

**Alternatives considered**：
- Server-Sent Events／WebSocket：被否決。專案內無任何既有用例，需新增
  連線管理與重連處理；而掃描進度的更新頻率極低（每筆 5–20 秒），
  推播帶來的即時性沒有實際價值。

---

## §6 速率守衛與 scraper 呼叫的歸屬

**Decision**：兩者都**留在 `flight_search.py` 內，不上移到 router 或
service**。router 只呼叫既有函式並讀取其回報的配額資訊。

**Rationale**：`flight_search.py` 已實作滾動小時速率守衛
（`read_browser_usage()`／`remaining_browser_quota()`／
`seconds_until_quota_frees()`）與 scraper 的 subprocess 呼叫，且皆有測試
覆蓋。速率限制是「查價這件事」的性質，不是 HTTP 層的性質；上移會讓同一
規則出現兩份實作（CLI 與網頁各一），必然分岔。

**Alternatives considered**：
- 在 router 層另做一套配額控制：被否決。CLI 與網頁會有不同的守衛行為，
  而兩者共用同一個外部服務與同一份用量紀錄檔。

---

## §7 追蹤條件的狀態：儲存或推導

**Decision**：**混合**。可由事實推導者不儲存（掃描中／排隊中／部分完成／
已完成），需要歷史才能判斷者才儲存（`last_success_at`）。

**Rationale**：`workflow-and-states.md` 定義的七個狀態中，前五個都能由
「未完成組合數」「目前是否有背景任務在跑」「本時段剩餘配額」即時算出；
唯有「資料過期」需要知道上次成功更新的時間，那無法從快取推導
（快取有價格但不知道是第幾輪寫的）。

**Alternatives considered**：
- 全部存成狀態欄位：被否決。狀態機的每次轉換都要正確寫入，漏寫即與事實
  不符；而推導的結果永遠與事實一致。
- 全部推導：被否決。「資料過期」判定不出來，會讓 FR 無法實作
  （過期時不得以舊價觸發通知——雖然通知屬第二個包，但過期標示屬本包）。

---

## 未解決事項

**無。** Technical Context 中沒有 NEEDS CLARIFICATION 項目；規格階段的
22 個釘清項目已於 pre-spec 全數解決。

以下兩項為**已知不確定性**，已在規格中明確標示為推估而非事實，
不阻擋實作：

| 項目 | 現況 | 處理方式 |
|---|---|---|
| 外部查價服務的確切速率上限 | 實測 52 與 205 筆/小時皆被阻擋；目前設 20 筆/小時為保守推估，未經長期驗證 | 介面顯示時標明為推估值（CON-09／FR-018）；值可由設定調整 |
| 促銷艙 travel validity 對間隔上限的影響 | 實測 90／120／150 天未觸發跳價，上限未知 | 不在系統內設限；由使用者自行從結果價格判斷 |
