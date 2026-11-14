# Contract: CLI／內部介面

## 1. 排程匯入 `poc/kb-mcp/investanchors_import.py`

```
python3 poc/kb-mcp/investanchors_import.py --data-dir <dir>
        [--dry-run] [--force-weekly] [--retranscribe] [--reset-abandoned <article_id>]
```
- `--data-dir` 預設 `poc/data`；指向正式庫需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`。
- 流程：(1) 讀 `import_runs`：`blocked_until` 未到 或 今日登入已達 2 次 → 寫一筆 `aborted_limit`／`none` 後結束，**不登入**。
  (2) 唯讀取信（失敗＝不觸發抓取，連續失敗才通知；每週核對仍會補漏）。 (3) 決定觸發：新信／週日核對／回補未完成；
  都沒有 → 寫 `trigger=none`，結束（SC-003：登入次數 0）。 (4) 組出待抓清單（`discovered`＋`failed` 且 attempts<3，
  上限 5 篇）。 (5) 啟動 scraper（見 §4），逐篇、隨機 30–90 秒間隔。 (6) **無論成敗**確認登出並記 `logged_out`。
  (7) 新文章 Telegram（標題＋連結，不含內文）；失敗類別通知（FR-020）。
- `--dry-run`：只取信＋列出將抓的 ID，**不登入、不寫入、不通知**。
- `--retranscribe`：只讀本機圖片檔補轉 `untranscribed`／換模型後重轉，**不登入網站**。
- Exit code：0＝正常（含無觸發）；1＝有失敗；2＝因上限／退避而拒絕（非錯誤，供健康檢查辨識）。
- 依賴注入點（測試用）：`fetch_mail`、`run_scraper`、`transcribe`、`notifier`、`get_secret`、`now`。

## 2. 探查工具 `poc/kb-mcp/article_probe.py`（Phase 0，PO 在場一次性）
```
python3 poc/kb-mcp/article_probe.py --data-dir poc/data --confirm-po-present
```
- 沒有 `--confirm-po-present` 直接拒絕執行。
- 硬上限：登入 1 次、清單 ≤3 頁、開文章 ≤2 篇；單一 context；結束登出並驗證登出。
- 輸出 `poc/data/articles_probe/probe-<時間>.json`：分頁型態、選擇器、通知信連結型態、登出方式、已讀是否改變、
  內文／圖片 DOM 結構。**不含全文、不含 cookie、不含帳密。**

## 3. 核對工具 `poc/kb-mcp/article_reconcile.py`（回補完成後，唯讀）
- 讀「總覽」清單所有頁（受同樣上限與間隔約束，可分多次），與 `article`（排除公告）逐篇比對，輸出缺漏／重複清單
  （SC-001）。不寫入 `article`；只輸出報告。

## 4. Scraper 協定 `scraper/investanchors_scraper.js`
- **stdin（單一 JSON）**：`{"mode":"list|articles","email":…,"password":…,"article_ids":[…],"max_pages":N,"delay_ms":[30000,90000],"image_dir":"…"}`
  — 帳密只經 stdin 傳遞，不出現在 argv／env／stderr。
- **stdout（JSON Lines）**：`{"type":"login","ok":bool,"reason":"bad_credentials|account_disabled|…"}`、
  `{"type":"list_item","article_id":…,"title":…,"date":…}`、
  `{"type":"article","article_id":…,"title":…,"date":…,"body":…,"images":[{"seq":1,"src_url":…,"file":…}]}`、
  `{"type":"article_error","article_id":…,"reason":"timeout|structure|no_body"}`、
  最後必有 `{"type":"summary","blocked":bool,"soft_blocked":bool,"logged_out":bool}`。
- 進度與診斷走 stderr，**不得含全文／帳密／cookie**。
- 被擋判定（任一即 `blocked=true` 並立刻結束）：連續 2 次逾時、被導向登入頁、非預期頁面。
- 一律 `finally` 區塊登出並 `context.close()`；`logged_out` 以「再訪登入頁出現登入表單」驗證。

## 5. Telegram 通知文字（沿用 `notify.send_telegram`，純文字）
- 新文章：`📰 定錨新文章：<標題>\n<url>`（只標題＋連結）。
- 需介入：`⚠️ 定錨匯入：<類別>`＋一句行動建議（登入失敗／帳號停用／被阻擋已延後／單篇放棄 <id>／頁面結構改變）。不含內文、帳密、cookie。
- 以 `alert_once(kind,key)` 同日去重。
