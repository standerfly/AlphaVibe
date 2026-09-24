# Quickstart: 單純來回機票搜尋

**Feature**: 008-roundtrip-search
**Date**: 2026-09-24

給接手實作或驗證此 feature 的人。**開工前必讀前兩節**——本 feature
大量重用 005／006／007 已完成的機制，不了解這點會重複實作既有邏輯。

## 1. 先確認你不需要寫什麼

以下**已完成且已對真實查價服務驗證過**，不要重寫：

| 既有能力 | 位置 | 重用方式 |
|---|---|---|
| `google_flights_url()` | `flight_search.py` | **不修改**，傳 2 段自動編碼來回、傳 4 段自動編碼多城市（research.md §1）——這是本 feature 最重要的一個發現，省掉一整條原本以為要開發的網址組法 |
| 瀏覽器查價、速率守衛、查價快取 | `flight_search.py` | 直接沿用，兩種 trip type 走同一套查價機制 |
| `combination_count()`／`MAX_COMBINATIONS_PER_TRACK` | `flight_scan_service.py`（007） | 直接呼叫，`num_targets` 傳候選目的地數 |
| `is_due()`／`next_scan_date()` | `flight_scan_service.py` | 直接呼叫，只依賴 id／scan_frequency_days／last_success_at |
| `should_notify()`／`should_notify_status()` | `flight_scan_service.py` | 直接呼叫，只依賴傳入的 lowest_price／state |
| `notify.send_telegram()` | `notify.py` | 直接沿用，訊息內容由新的 build_roundtrip_notification() 產生 |

**唯一需要真實瀏覽器驗證、不能只憑讀程式碼斷定的事**：scraper
（`flight_scraper.js`）對「2 段來回」查詢頁面的相容性
（research.md §1「尚待驗證」段落）。實作 US1 時第一件要做的驗證，
不是留到最後。

## 2. 要寫的檔案

```text
poc/kb-mcp/flight_store.py            # 新增 roundtrip_track／
                                        # roundtrip_scan_result 兩張表
                                        # 與 CRUD 方法（見 data-model.md）
poc/kb-mcp/flight_scan_service.py     # 新增 roundtrip 版本的展開邏輯、
                                        # build_roundtrip_notification()／
                                        # build_roundtrip_status_notification()
poc/kb-mcp/flight_tracking_job.py     # 排程迴圈擴充涵蓋兩張表
app/routers/flights.py                # 新增 roundtrip 端點群（見
                                        # contracts/roundtrip-api.md），
                                        # 既有清單端點改為合併回傳
web/src/pages/Flights.jsx             # 類型切換 UI
web/src/pages/FlightTrackForm.jsx     # 單純來回建立表單
```

**不要動**：`flight_search.py`、`flight_store.py` 既有的
`flight_track`／`flight_scan_result` 相關方法、既有四段票的
API 端點本身（`POST/PATCH/DELETE /api/flights/tracks/{id}`）。

## 3. 兩個容易踩的坑

**坑 1：`roundtrip_track` 與 `flight_track` 的 id 可能相同數字**

兩張表各自 `AUTOINCREMENT`，id=3 可能同時存在於兩張表，代表不同的
條件。API 用路徑區分（`/api/flights/tracks/roundtrip/{id}/...`），
前端渲染清單時**務必用 `track_type` 欄位決定要打哪個端點**，不能
只憑 id 判斷（contracts/roundtrip-api.md 已說明命名理由）。

**坑 2：組合數上限守衛不能只套在四段票的建立路徑**

`app/routers/flights.py` 的既有 `create_track()`（四段票）已經在
呼叫 `combination_count()` 做上限檢查；新的 roundtrip 建立端點
**必須獨立呼叫同一套檢查**，不會因為共用同一個 `combination_count()`
函式就自動套用到新端點——這是兩個不同的 HTTP handler，各自要顯式
呼叫驗證邏輯。

## 4. 本機開發與驗證

```bash
# 單元測試
.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"

# smoke test（乾淨測試庫，步驟見 CLAUDE.md「STND（app/）驗證」節）
rm -rf poc/data-test && cp -R poc/data poc/data-test
# 清空 asset_* 表與 sqlite_sequence（見 CLAUDE.md 既有步驟）
rm -f poc/data-test/flights.db
ALPHAVIBE_DATA_DIR=$(pwd)/poc/data-test .venv/bin/python3 -m app.tests.test_smoke
```

**驗證 scraper 對來回頁面的相容性**（坑 1 提到的尚待驗證項目）：
用既有的組合數配額守衛先佔滿配額（`fs.record_browser_usage()`，
smoke test 已有這個模式可參考），或直接對測試目錄跑一次真實的
2 段查詢，確認能正確抓到價格且不誤判成多城市頁面。

## 5. 正式環境部署順序

本包**不涉及對既有生產資料的破壞性異動**（與 007 不同——007 要遷移
既有 id=9，本包只是新增兩張空表），部署風險較低：

1. 合併程式碼到 `function/alphavibe`
2. 重啟 `com.alphavibe.reportserver`（`_migrate()` 會自動建立新表，
   不需要額外遷移腳本）
3. 用 `curl` 建立一個真實的單純來回條件、觸發掃描，確認端到端運作
4. 確認既有四段票條件（例如 id=9）在合併後仍正常運作——本包理論上
   不動既有四段票程式碼，但清單端點的合併邏輯是共用程式碼，需要
   實際驗證不會不小心影響到既有行為
