# Quickstart: 機票掃描分頁

**Feature**: 005-flight-scan-page
**Date**: 2026-09-23

給接手實作或驗證此 feature 的人。**開工前必讀前兩節**——本 feature 建立在
已完成的查價能力之上，不了解這點會重複實作既有邏輯。

## 1. 先確認你不需要寫什麼

以下**已完成且經真實查價驗證**，不要重寫：

| 既有能力 | 位置 | 狀態 |
|---|---|---|
| 四段票行程枚舉（月掃描／固定主行程兩種模式） | `poc/kb-mcp/flight_search.py` | 112 測試 |
| 日期抽樣（`sample_dates`） | 同上 | 已測 |
| 兩端間隔挑選（`pick_lead`／`pick_trail`） | 同上 | 已測 |
| 查價網址構造（protobuf 編碼） | 同上 `google_flights_url()` | 已對真實服務驗證 |
| 瀏覽器查價（含節流、軟阻擋偵測、逐筆落地） | 同上 `scrape_itineraries()` ＋ `scraper/` | 已對真實服務驗證 |
| 滾動小時速率守衛 | 同上 `remaining_browser_quota()` 等 | 已測 |
| 查價快取 | `poc/data/flight_cache/`（44 筆真實資料） | 運作中 |

背景與實測記錄：`docs/research/2026-09-22-ex-station-4segment-ticket-search.md`
（943 行）。**該文件第 14、18、20 節記錄了三次「從不足樣本外推出過強結論」
的判斷失誤**，實作時若要調整速率相關參數，先讀那三節。

## 2. 要寫的三個新檔案

```text
poc/kb-mcp/flight_store.py            # 兩張表的持久化（獨立 flights.db）
poc/kb-mcp/flight_scan_service.py     # 條件→組合、未完成推導、續掃、狀態判定
app/routers/flights.py                # HTTP 層（見 contracts/flights-api.md）
app/flight_deps.py                    # 依賴注入 ＋ 背景任務用的資料目錄解析
web/src/pages/Flights.jsx             # 分頁主畫面
web/src/pages/FlightTrackForm.jsx     # 條件表單
```

## 3. 三個容易踩的坑（皆為專案內已發生過的事故）

**坑 1：背景任務不能用 request-scoped 的 store 依賴**
`Depends(get_flight_store)` 的連線在 response 送出後可能已被 `finally`
關閉。背景任務必須改用 `resolve_flight_data_dir_for_background()` 自行開關
連線。出處：`app/routers/photos.py` docstring。

**坑 2：`sqlite3.connect` 必須帶 `check_same_thread=False`**
FastAPI 的 sync generator dependency 由 anyio thread pool 執行，建立與關閉
不保證同一條 thread。2026-08-22 正式環境 30 個併發請求有 23 個 500。
出處：`kb_store.py:372`、`CLAUDE.md` 教訓紀錄。
**且必須寫併發測試**——當次事故的深度測試全是依序單一請求，完全沒測到。

**坑 3：`__init__()` 不得有寫入副作用**
`kb_store.py` 曾因建構子內自動寫入種子資料，污染正式資料庫兩次。
`FlightStore.__init__()` 只建表，不寫任何資料列。

## 4. 本機開發與驗證

```bash
# 依賴（scraper 已有 node_modules；若無）
cd poc/kb-mcp/scraper && npm install && cd -

# 單元測試（資料層與服務層）
.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"

# 路由層 smoke test（含併發）——務必指向獨立測試庫，不可指向 poc/data
rm -rf poc/data-test && cp -R poc/data poc/data-test
ALPHAVIBE_DATA_DIR=poc/data-test .venv/bin/python3 -m app.tests.test_smoke
```

`app/tests/test_smoke.py` 對測試庫**不是冪等的**，且要求乾淨的資產表。
完整重建步驟見 `CLAUDE.md`「STND（app/）驗證」一節，少任何一步都會 FAIL。

## 5. 驗證功能實際可用（非僅測試通過）

掃描會真的連線外部服務並消耗配額，因此：

```bash
# 先看要掃什麼、要多久、配額夠不夠（不發任何請求）
.venv/bin/python3 poc/kb-mcp/flight_search.py --scan-dates \
  --destination PRG --outstations NRT,OKA \
  --start-date 2027-04-01 --months-ahead 3 --per-month 2 --trip-days 12 \
  --lead-days 210,180,150,120,90 --exclude-lead-months 6,7,8 \
  --trail-days 120,90,60,30 --exclude-trail-months 6,7,8 \
  --data-dir poc/data --dry-run
```

`--dry-run` 不需要任何憑證、不發請求、不耗配額。實際掃描請控制規模——
**目前速率上限為推估值（20 筆/小時），超量會被靜默阻擋成連續逾時**。

## 6. 交付邊界

| 屬本 feature | 不屬本 feature |
|---|---|
| 條件 CRUD、掃描、結果顯示、兩端間隔策略、速率守衛可視化、外部連結、票規提示 | 定期自動重掃、達標通知、Telegram 推播、資料過期的通知抑制 |

目標價欄位在本 feature **僅儲存與顯示，不觸發任何通知**。通知屬
`flight-price-tracking`（pre-spec handoff order 2）。

## 7. 相關文件

| 文件 | 用途 |
|---|---|
| `spec.md` | 26 條 FR、4 個 user story 切片、9 個成功標準 |
| `plan.md` | 技術脈絡、憲章檢核狀態、目錄結構決策 |
| `research.md` | 7 項實作決策與被否決的替代方案 |
| `data-model.md` | 兩張表、驗證規則、狀態推導方式 |
| `contracts/flights-api.md` | 6 個端點的請求與回應 |
| `../../docs/spec-intake/flight-search/product-spec.md` | 上游需求基線（Accepted） |
| `../../docs/spec-intake/flight-search/supporting-artifacts/workflow-and-states.md` | 狀態機與掃描序列圖 |
