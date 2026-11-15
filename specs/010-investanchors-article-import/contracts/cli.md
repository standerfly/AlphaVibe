# Contract: CLI／內部介面

## 1. 排程匯入 `poc/kb-mcp/investanchors_import.py`

```
python3 poc/kb-mcp/investanchors_import.py --data-dir <dir>
        [--dry-run] [--force-weekly] [--max-articles N] [--resume] [--retranscribe]
        [--reset-abandoned <article_id>] [--backfill-since <YYYY-MM-DD>]
        [--enable-transcription | --disable-transcription] [--retranscribe] [--transcribe-sample N]
```
- `--backfill-since <日期>`：**PO 要求補抓更早文章時**使用。把 `backfill_state.cutoff_date`／`cutoff_ms` 放寬到該日期、
  `completed` 重設為 0，並把 ID 建立時間落在新舊截止日之間的 `deferred` 文章轉回 `discovered`；之後仍依每日 5 篇
  上限慢慢補。只能「往前放寬」（新日期早於現有截止日），否則拒絕；**放寬回補範圍＝放寬低頻負擔，須 PO 同意**。
- 回補清單讀取：從最新一頁往舊翻；某一頁**所有「非置頂、非公告」文章的 ID 建立時間都早於 截止日−14 天**即停止，
  不再往更舊翻（比全量更低頻）。**不使用清單日期**（置頂的近期文章清單日期會顯示 2021 年）；置頂項＝同一 ID
  在第 1、2 頁重複出現者（實測每頁頂端 5 筆），**不得被當舊文跳過、也不參與停止判斷**；不依賴清單位置，一律以 ID 為準。
  防呆：ID 不是 14 位數或換算時間不合理 → 該篇不得判為「早於截止日」，照常處理並記 `id_time_ok=0`，累計超過 3 篇通知 PO。
- 標題取自清單連結文字（通知信主旨為輔）；文章頁只取內文容器 `div#inves_content`、發布時間 `span.post_date`、
  內文容器內的圖片（記 `src_url`）。圖片不帶 cookie 即可下載：登出後由 Python 以 HTTP 下載，**不算登入次數，
  但每張之間仍隨機間隔 5～15 秒**；一篇可能只有 1 張長圖，轉寫前依 research R5 的原則切片。
- `--data-dir` **必填、無預設值**；解析（realpath，含 AlphaVibe-prod 的 symlink）後若是正式資料目錄，需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`，否則在取信、登入、寫入之前拒絕（`--dry-run`、`--resume` 等也一樣）。判斷邏輯在 `article_data_guard.py`，CLI（含 `article_probe.py`）與 `app/article_deps.py` 共用。
- 流程：(1) 讀 `import_runs`：`blocked_until` 未到 或 今日登入已達 1 次 → 寫一筆 `aborted_limit`／`none` 後結束，**不登入**。
  (2) 唯讀取信：**只取 Message-ID 與寄達時間**，不解析、不記錄信中連結與標題（失敗＝不因信觸發，連續失敗才通知；每週
  核對仍會登入）。 (3) 決定觸發：有未處理的新信／週日核對（保底）／回補未完成；都沒有 → 寫 `trigger=none`，結束
  （SC-003：登入次數 0）。 (4) 登入後讀清單第 1 頁，必要時往後翻到「一頁內非置頂項全部已入庫」為止，組出待抓清單：
  **清單上所有未入庫的文章 ID**（不論有無對應通知信）＋`failed` 且 attempts<3；**新文章優先於回補**，上限 5 篇。 (5) 啟動 scraper（見 §4），逐篇、隨機 30–90 秒間隔。 (6) **無論成敗**確認登出並記 `logged_out`。
  (7) 新文章 Telegram（標題＋連結，不含內文）；失敗類別通知（FR-020）。
- `--dry-run`：只取信＋列出觸發判斷，**不登入、不寫入、不通知、不建立資料庫檔**（資料庫不存在時改用暫存目錄）。
- `--resume`：帳號停用（`account_disabled`）時協調器會寫入 `setting.halted_reason` 並**停止後續排程**（直到 PO 處理）；排除後用此旗標恢復。
- 每週核對觸發：週日且上次核對 ≥6 天前；**或超過 8 天沒核對**（週日那次因睡眠錯過時的保底）。
- 信箱讀取連續失敗 3 次才通知（`setting.mail_fail_count`）；單次失敗不因信觸發，但每週核對照常登入。
- `--retranscribe`：只讀本機圖片檔補轉 `untranscribed`／換模型後重轉，**不登入網站**；**轉寫開關關閉時拒絕（exit 2，訊息「轉寫開關未開」）**。
- `--enable-transcription`／`--disable-transcription`：切換 `setting.transcribe_enabled`（冪等、印出目前狀態、只改設定）。**預設關閉（無 `transcribe_enabled` 列＝關）**；關閉時匯入流程不呼叫模型 API、也不讀取 `vision-api-key`；切換旗標不取信、不登入，且不可與其他動作旗標併用（exit 2）。開啟後匯入流程逐圖轉寫（`is_table=false` 記 `not_table`、失敗留 `untranscribed`；某張遇金鑰／額度問題即中止本次後續圖，其餘待 `--retranscribe`）。
- `--transcribe-sample N`：從本機已下載的圖隨機抽 N 張（**須含至少 1 張長圖**，長圖＝高/寬 ≥1.5 且高度 ≥2000px；庫內不足就回報不足與現況）轉寫，結果只寫進 `<data-dir>/articles_probe/transcribe-sample-<時間>.md`（正式庫即 `poc/data/articles_probe/`，已被 gitignore）供 PO 逐格比對；每張圖列出 article_id／seq、尺寸、原圖路徑與轉寫文字（不含標題、內文、金鑰），**不寫入資料庫**；不登入網站；開關關閉時仍可執行（唯一例外）。
- Exit code：0＝正常（含無觸發）；1＝有失敗；2＝因上限／退避而拒絕（非錯誤，供健康檢查辨識）。
- 依賴注入點（測試用）：`fetch_mail`、`run_scraper`、`transcribe`、`notifier`、`get_secret`、`now`。

## 2. 探查工具 `poc/kb-mcp/article_probe.py`（Phase 0，PO 在場一次性）
```
python3 poc/kb-mcp/article_probe.py --data-dir poc/data --confirm-po-present --confirm-one-device-only
```
- 沒有 `--confirm-po-present` 或 `--confirm-one-device-only`（PO 確認電腦瀏覽器已登出、只剩手機一台）直接拒絕執行（拒絕時**不讀鑰匙圈、不連線**）。其他旗標：`--base-url`（預設
  `https://investanchors.com`）、`--skip-mail`（略過 P4 通知信連結檢查）、`--verbose`。頁面間隔固定 30～90 秒
  （下限 10 秒，不可由 CLI 調低）。
- 實作狀態（2026-11-15）：`article_probe.py`＋`scraper/investanchors_scraper.js`（probe 模式）＋
  `tests/test_article_probe.py` 已完成並通過測試；**尚未對真實網站執行**。
- **純信箱模式（不登入定錨網站、不啟動瀏覽器）**：`article_probe.py --mail-only --confirm-mail-read [--mail-days 30] [--list-report <第二次探查報告>]`。只讀 `stnd-statement-import` 的 Gmail 憑證（不讀 `stnd-investanchors`），唯讀、`BODY.PEEK`、不標已讀、不跟隨任何連結；沒有 `--confirm-mail-read` 即拒絕且不讀憑證。輸出 `mail-<時間>.json`：每封信的寄達日期（換成台北日期）、連結分類、站內連結**路徑形態**（數字換成 `#`）、查詢參數**名稱**（不含值）、信中長數字（疑似文章 ID）的個數，以及它們有幾個對得上清單上的 ID（**只回數量**）；並與第二次探查的清單逐項日期做**只比日期、不記標題**的比對（每日信件數 vs 文章數、無信文章數、一封信含多篇的封數）。置頂項用 ID 推得的建立日期。
- 探查前先找伺服器端登出機制；找不到即停止、不開任何文章、報告 `no_logout_mechanism`。
- 登入表單：以第一個**可見**密碼欄位所屬 form 為準，其餘欄位與送出鈕限定在該 form 內；該 form 看起來像註冊表單
  （文字欄位 >2 或密碼欄位 ≠1）或找不到 form → `ambiguous_login_form`，不送出。
- 登出依序嘗試並**每步後驗證**：(a) 展開使用者選單再點 (b) 頁面內 `el.click()` (c) 讀 `data-method`＋CSRF token 以同源請求送出
  對應方法（POST＋`_method` 覆寫，並補送真實 DELETE／PUT／PATCH）(d) GET；token 不離開頁面、不寫入報告。
- 任何異常路徑、以及收到 SIGINT／SIGTERM／SIGHUP，只要已送出登入表單或頁面找得到登出機制，就先登出再結束
  （已關閉 Playwright 內建的訊號處理，否則它會先關瀏覽器導致無法登出）。
- Python 端有看門狗整體逾時：到時先送 SIGTERM（讓 Node 登出），寬限後才 kill。
- 登出未驗證時，工具訊息為「探查的登入狀態可能仍留在伺服器端，PO 在自己裝置登出無法清除；請勿再次執行探查，先回報」。
- `www.investanchors.com` 與 `investanchors.com` 視為同站。
- 硬上限：登入 1 次、清單 ≤3 頁、開文章 ≤2 篇；單一 context；結束登出並驗證登出。
- 輸出 `poc/data/articles_probe/probe-<時間>.json`：分頁型態、選擇器、通知信連結型態、登出方式、已讀是否改變、
  內文／圖片 DOM 結構。**不含全文、不含 cookie、不含帳密。**

## 3. 核對工具 `poc/kb-mcp/article_reconcile.py`（回補完成後，唯讀）
- 讀「總覽」清單到「整頁都早於截止日」為止（受同樣上限與間隔約束，可分多次），與 `article`（排除公告）
  中發布日期在半年內者逐篇比對，輸出缺漏／重複清單（SC-001）；早於截止日的只確認為 `deferred`。不寫入 `article`；只輸出報告。

## 4. Scraper 協定 `scraper/investanchors_scraper.js`
- **import 模式（T013／T014 已實作）**：stdin `{"mode":"import","email":…,"password":…,"base_url":…,"known_ids":[…],"pending_ids":[…],"max_list_pages":≤3,"max_articles":≤5,"delay_ms":[30000,90000],"timeout_ms":N}`；單一登入 session 內：讀清單第 1 頁（必要時往後翻到「一頁內非置頂、非公告項目全部已知」為止）→ 目標＝清單上所有未入庫的 ID（含置頂）＋`pending_ids`，新文章在前、受 `max_articles` → 逐篇開啟 → 登出並驗證。stdout JSONL：`fact(login)`、`list_item{page,article_id,title,date,is_announcement,read_state,pinned}`、`fact(targets)`、`article{article_id,published_at,body,images[{seq,src_url}]}`、`article_error{article_id,reason:structure|short|timeout}`、`summary`。內文過短（<200 字）或缺 `div#inves_content` 一律輸出 `article_error`，**不輸出殘缺內文**；`pinned`＝同一 ID 在相鄰頁重複出現。
- **stdin（單一 JSON）**：`{"mode":"list|articles","email":…,"password":…,"article_ids":[…],"max_pages":N,"delay_ms":[30000,90000],"image_dir":"…"}`
  — 帳密只經 stdin 傳遞，不出現在 argv／env／stderr。（上一條的 import 模式取代 list／articles 兩個獨立模式的原構想。）
- **stdout（JSON Lines）**：`{"type":"login","ok":bool,"reason":"bad_credentials|account_disabled|…"}`、
  `{"type":"list_item","article_id":…,"title":…,"date":…}`、
  `{"type":"article","article_id":…,"title":…,"date":…,"body":…,"images":[{"seq":1,"src_url":…,"file":…}]}`、
  `{"type":"article_error","article_id":…,"reason":"timeout|structure|no_body"}`、
  最後必有 `{"type":"summary","blocked":bool,"soft_blocked":bool,"logged_out":bool}`。
- 進度與診斷走 stderr，**不得含全文／帳密／cookie**。
- 被擋判定（任一即 `blocked=true` 並立刻結束）：連續 2 次逾時、被導向登入頁、非預期頁面。
- 一律 `finally` 區塊登出並 `context.close()`；`logged_out` 以「再訪登入頁出現登入表單」驗證。

## 5. Telegram 通知文字（沿用 `notify.send_telegram`，純文字）
- 新文章（建立時間距抓取當下 ≤7 天，`id_time_ok=0` 視為近期）：`📰 定錨新文章：<標題>\n<url>`（只標題＋連結），逐篇一則。
- 較早的文章（>7 天）：每次執行合併一則 `📰 定錨補抓：已補抓 N 篇較早的文章`，不列標題。
- 需介入：`⚠️ 定錨匯入：<類別>`＋一句行動建議（登入失敗／帳號停用／被阻擋已延後／單篇放棄 <id>／頁面結構改變）。不含內文、帳密、cookie。
- 以 `alert_once(kind,key)` 同日去重。
