# Quickstart: 四段票天數區間化

**Feature**: 007-trip-day-range
**Date**: 2026-09-24

給接手實作或驗證此 feature 的人。**開工前必讀前兩節**——本 feature 是對
005／006 已上線功能的升級，不了解這點會重複實作既有邏輯，或改壞正式
環境已在運作的追蹤條件。

## 1. 先確認你不需要寫什麼

以下**已完成且已對真實查價服務驗證過**，不要重寫：

| 既有能力 | 位置 | 狀態 |
|---|---|---|
| 四段票行程枚舉（`sample_dates`／`build_itineraries_fixed_trip`） | `poc/kb-mcp/flight_search.py` | 已測，本次不修改 |
| 兩端間隔挑選（`pick_lead`／`pick_trail`／`_resolve_offsets`） | `flight_search.py`／`flight_scan_service.py` | 已測，不依賴 `trip_days`，本次不修改（research.md §5） |
| 查價網址構造、瀏覽器查價、速率守衛、查價快取 | 同上 | 已對正式環境驗證，本次不修改 |
| 排程（`flight_tracking_job.py`）、通知判定（`should_notify`／`should_notify_status`）、過期防護（`derive_state`） | `flight_scan_service.py`／`flight_tracking_job.py` | 已上線運作中，預期不需修改，但需驗證（見第 3 節坑 2） |
| 航空公司聯盟顯示（`describe_airlines`） | `flight_search.py` | 已上線，與天數無關，不受影響 |

背景：`docs/spec-intake/flight-roundtrip-search/`（本次 pre-spec 完整
記錄，含 PO 決策脈絡）、`specs/005-flight-scan-page/`、
`specs/006-flight-price-tracking/`（既有功能的技術規格）。

## 2. 要動的檔案

```text
poc/kb-mcp/flight_store.py            # schema 新增 2 欄位、create_track 驗證改區間、
                                        # 新增 update 相關方法（若需要）
poc/kb-mcp/flight_scan_service.py     # expand_track() 天數迴圈、新增組合數計算純函式
poc/kb-mcp/migrate_trip_days_range.py # 新增：id=9 一次性遷移腳本
app/routers/flights.py                # 建立條件的請求／回應欄位改區間、組合數上限驗證
web/src/pages/FlightTrackForm.jsx     # 天數欄位改兩個輸入框（下限／上限）
web/src/pages/Flights.jsx             # 天數顯示改區間格式
poc/kb-mcp/tests/test_flight_store.py
poc/kb-mcp/tests/test_flight_scan_service.py
app/tests/test_smoke.py               # 既有 trip_days 深度比對斷言需同步更新
```

**不要動**：`flight_search.py` 的 `sample_dates()`／
`build_itineraries_fixed_trip()`／`pick_lead()`／`pick_trail()`；
`flight_tracking_job.py` 的排程選取邏輯（`is_due`／`next_scan_date`）。

## 3. 三個容易踩的坑

**坑 1：SQLite 的 `ADD COLUMN` 是唯一安全的 schema 異動方式**

這個 repo 的既有 migration 慣例（`flight_store.py::_migrate()`）只用
`ALTER TABLE ... ADD COLUMN` 並容忍「欄位已存在」的 `OperationalError`。
**不要**嘗試 `DROP COLUMN` 或改變既有欄位型別／約束——即使新版 SQLite
支援，也偏離這個 repo 一貫只加不減的謹慎慣例（research.md §2）。舊的
`trip_days` 欄位保留在 schema 但停止被讀取，新建列時鏡射寫入
`trip_days_max` 純粹是為了滿足既有 `NOT NULL` 約束。

**坑 2：排程／通知／過期防護沿用既有邏輯是一個待驗證的假設，不是保證**

`spec.md` 的 Assumptions 明確寫「假設」，不是「確認」。`should_notify()`／
`derive_state()` 等函式的簽章與判定邏輯基於「最低價」「組合數」「已完成
數」這類抽象值，理論上不關心 `trip_days` 是單一值還是區間展開出的多筆
結果，但**必須實際跑過整合測試（含 id=9 遷移後的真實排程觸發）才能
確認**，不能只憑閱讀程式碼就假設沒問題。

**坑 3：id=9 是正式環境真實在用的資料，遷移前務必先在測試庫驗證**

遷移腳本 `migrate_trip_days_range.py` **第一次執行必須先對著
`poc/data-test/`（獨立測試庫）跑過、確認行為正確，才能對 `poc/data/`
（正式庫）執行**。比照 CLAUDE.md 記載的既有測試庫重建步驟（`rm -rf
poc/data-test && cp -R poc/data poc/data-test`）。

**發現的既有缺口**：`poc/kb-mcp/backup_databases.py` 的
`DATABASES = ("alphavibe.db", "us_stocks.db")` **不含 `flights.db`**
——機票功能是 2026-09-23 才上線，還沒被納進既有的每日自動備份
（`com.alphavibe.dbbackup.plist`）。既然本次要對 `flights.db` 做
schema 遷移，順手把它加進 `DATABASES` 是低成本、直接保護這次異動的
修正（一行改動），建議在本 feature 的任務中一併處理，而不是只做一次性
手動備份了事。

## 4. 本機開發與驗證

```bash
# 單元測試
.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"

# smoke test（乾淨測試庫，步驟見 CLAUDE.md「STND（app/）驗證」節）
rm -rf poc/data-test && cp -R poc/data poc/data-test
# 清空 asset_* 表與 sqlite_sequence（見 CLAUDE.md 既有步驟）
rm -f poc/data-test/flights.db   # 機票是獨立 db，測試庫清空重建
ALPHAVIBE_DATA_DIR=$(pwd)/poc/data-test .venv/bin/python3 -m app.tests.test_smoke

# 遷移腳本先對測試庫驗證
.venv/bin/python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data-test --dry-run
.venv/bin/python3 poc/kb-mcp/migrate_trip_days_range.py --data-dir poc/data-test
```

## 5. 正式環境部署順序

1. 備份 `poc/data/flights.db`
2. 合併程式碼到 `function/alphavibe`，重啟 `com.alphavibe.reportserver`
3. 對正式庫執行 `migrate_trip_days_range.py`（先 `--dry-run` 確認，
   再真正執行）
4. 觸發 id=9 的手動掃描，確認新的 10～14 天組合能正常查價
5. 用 `curl` 直接打正式 API 確認 `trip_days_min`／`trip_days_max` 欄位
   正確回傳（比照本 session 過去對 005／006／通知功能的正式環境驗證
   慣例，不只信任單元測試）
