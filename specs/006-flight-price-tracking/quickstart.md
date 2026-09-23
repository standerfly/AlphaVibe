# Quickstart: 機票價格追蹤與通知

**Feature**: 006-flight-price-tracking
**Date**: 2026-09-23

## 1. 先確認你不需要寫什麼

| 既有能力 | 位置 | 狀態 |
|---|---|---|
| 查詢條件、組合枚舉、查價、配額守衛、狀態推導 | `flight_scan_service.py`／`flight_search.py` | 005 完成，178 測試，已真實查價驗證 |
| Telegram 推播 | `poc/kb-mcp/notify.py::send_telegram()` | 2026-09-17 建立的共用模組，直接複用 |
| 查價連結構造 | `flight_search.google_flights_url()` | 005 完成 |

本功能只做兩件事：**什麼時候跑**、**跑完要不要通知**。

## 2. 要寫的檔案

```text
poc/kb-mcp/flight_tracking_job.py    # 新增：launchd 的進入點
poc/kb-mcp/flight_store.py           # 既有：4 個新欄位
poc/kb-mcp/flight_scan_service.py    # 既有：達標判定與通知決策
app/routers/flights.py               # 既有：PATCH 端點與新欄位
web/src/pages/Flights.jsx            # 既有：顯示排程與通知狀態
web/src/pages/FlightTrackForm.jsx    # 既有：頻率選項
~/Library/LaunchAgents/com.alphavibe.flighttracking.plist   # 新增
```

## 3. 三個容易踩的坑

**坑 1：`derive_state()` 的過期週期寫死 7 天**
005 的實作是 `period_days=7`。本功能讓使用者設定頻率後，過期判定必須跟著
該條件的實際週期走——否則「每月一次」的條件會在第 15 天被誤判為過期
（`research.md` §4）。

**坑 2：排程腳本不要走 `app/flight_deps.py` 的環境變數防呆**
那道防線是為網頁服務設的（2026-08-22 測試埠寫進正式庫的事故）。排程腳本
用 `--data-dir` 參數，比照 `market_scan.py`／`us_stock_scan.py` 的既有做法
（`research.md` §6）。

**坑 3：通知失敗不得影響掃描**
`notify.py` 的設計鐵則就是「任何失敗都不讓呼叫端崩潰」，它回傳
`(成功數, [錯誤])` 而不拋例外。不要在外面加 try/except 以外的重試邏輯——
FR-011 明確要求通知失敗不重試掃描。

## 4. 本機驗證

```bash
# 單元測試
.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests -p "test_flight*"

# 排程腳本乾跑（不實際查價、不發通知）
.venv/bin/python3 poc/kb-mcp/flight_tracking_job.py --data-dir poc/data --dry-run

# smoke test（含併發）
rm -rf poc/data-test && cp -Rp poc/data poc/data-test
ALPHAVIBE_DATA_DIR=poc/data-test ALPHAVIBE_ALLOW_NO_AUTH=1 \
  .venv/bin/python3 -m app.tests.test_smoke
```

`cp -Rp` 的 `-p` 是必要的——不保留時間戳的話，配額檔的 mtime 會變成
「現在」，舊格式的用量會被誤判為剛發生（005 踩過）。

## 5. 通知的實際驗證

通知需要 `~/.config/stnd-gateway/.env` 有 `TELEGRAM_BOT_TOKEN` 與
`ALLOWED_USER_IDS`。沒有設定時 `send_telegram()` 回
`(0, ["Telegram 未設定…"])`，功能會正常降級（掃描照做、標示通知未送達），
不會崩潰——這本身也是值得驗證的行為。

## 6. 交付邊界

| 屬本 feature | 不屬本 feature |
|---|---|
| 自動重掃排程、達標通知、過期防護、頻率設定 | 查詢條件的建立與刪除、掃描本身、結果呈現（皆屬 005） |
