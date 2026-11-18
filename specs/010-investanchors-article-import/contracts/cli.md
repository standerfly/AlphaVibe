# Contract: CLI／內部介面

## 1. 排程匯入 `poc/kb-mcp/investanchors_import.py`

```
python3 poc/kb-mcp/investanchors_import.py --data-dir <dir>
        [--dry-run] [--force-weekly] [--max-articles N] [--resume] [--retranscribe]
        [--reset-abandoned <article_id>] [--backfill-since <YYYY-MM-DD>]
        [--enable-transcription | --disable-transcription] [--retranscribe] [--transcribe-sample N]
        [--export-untranscribed [--limit N]] [--import-transcription <results.json> [--apply] [--overwrite]]
        [--import-verification <verification.json> [--apply]] [--mark-reviewed <image_id[,image_id…]> [--apply]]
        [--export-verification-task [--limit N] [--only-unverified]]
```
- `--backfill-since <日期>`：**PO 要求補抓更早文章時**使用。把 `backfill_state.cutoff_date`／`cutoff_ms` 放寬到該日期、
  `completed` 重設為 0，並把 ID 建立時間落在新舊截止日之間的 `deferred` 文章轉回 `discovered`；之後仍依每日 5 篇
  上限慢慢補。只能「往前放寬」（新日期早於現有截止日），否則拒絕；**放寬回補範圍＝放寬低頻負擔，須 PO 同意**。
- 回補清單讀取（2026-11-15 加強）：每次登入讀第 1 頁（新文章與置頂）＋從 `next_cursor` 起最多 2 頁（`?page=N` 直接跳頁，
  合計 ≤3 頁）；**連續 2 頁**所有「非置頂、非公告」文章的 ID 建立時間都早於 截止日−14 天才停止往更舊翻
  （只有 1 頁符合就繼續；清單順序不穩，不假設「某頁全舊後面更舊」）。**不使用清單日期**（置頂的近期文章清單日期會顯示 2021 年）；置頂項＝同一 ID
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
- `--reset-transcribe-attempts`：**只能與 `--retranscribe` 併用**（否則 exit 2），把未轉寫圖的失敗次數歸零後再重試。
- **夜間補轉（2026-11-15 審查決定）**：轉寫開關開啟時，每次排程執行在新文章轉寫之後（含「無觸發」那次），另補轉最多 10 張（`BACKFILL_TRANSCRIBE_PER_RUN`）先前 `untranscribed` 的圖，順序為失敗次數少者先、再依 article_id／seq；單張累計失敗達 3 次（`MAX_TRANSCRIBE_ATTEMPTS`）後只有手動 `--retranscribe` 會再試；金鑰／額度 abort 後本次停止、未送出者不計次；開關關閉時不補轉、不計次、不呼叫模型、不讀 `vision-api-key`。
- `--enable-transcription`／`--disable-transcription`：切換 `setting.transcribe_enabled`（冪等、印出目前狀態、只改設定）。**預設關閉（無 `transcribe_enabled` 列＝關）**；關閉時匯入流程不呼叫模型 API、也不讀取 `vision-api-key`；切換旗標不取信、不登入，且不可與其他動作旗標併用（exit 2）。開啟後匯入流程逐圖轉寫（`is_table=false` 記 `not_table`、失敗留 `untranscribed`；某張遇金鑰／額度問題即中止本次後續圖，其餘待 `--retranscribe`）。
- `--transcribe-sample N`：從本機已下載的圖隨機抽 N 張（**須含至少 1 張長圖**，長圖＝高/寬 ≥1.5 且高度 ≥2000px；庫內不足就回報不足與現況）轉寫，結果只寫進 `<data-dir>/articles_probe/transcribe-sample-<時間>.md`（正式庫即 `poc/data/articles_probe/`，已被 gitignore）供 PO 逐格比對；每張圖列出 article_id／seq、尺寸、原圖路徑與轉寫文字（不含標題、內文、金鑰），**不寫入資料庫**；不登入網站；開關關閉時仍可執行（唯一例外）。
- **方案 D 手動轉寫（Phase 10，Q-027）**——免 API 金鑰，由 agent 讀圖；**零網路、零鑰匙圈、不登入、不取信、不通知**：
  - `--export-untranscribed [--limit N]`：**唯讀**開庫（庫不存在回 exit 1、不建庫），把「未轉寫（`untranscribed`）、有本機檔、所屬文章非 `abandoned`、檔案存在且可讀」的圖依 `article_id`／`seq` 穩定排序取前 N 張（預設 10，範圍 1～100，否則 exit 2），輸出到 `<data-dir>/articles_probe/manual-transcribe-<YYYYMMDD-HHMMSS>/`（同秒重複會加 `-2`，不覆蓋）：`manifest.json`（每項：`image_id`／`article_id`／`seq`／原圖絕對路徑 `path`／`sha256`／`width`／`height`／`is_long`／`transcription_status`／`tile_status`（`not_needed`｜`ok`｜`unavailable`）／`tile_reason`／`tiles`／`view_files`；**不含標題與內文、不含網址**）、`AGENT_GUIDE.md`、長圖切片 `tiles/<image_id>-<序>.png`（重用 `article_image_tiles.open_tiles`；沒有 Playwright／瀏覽器或片數過多時**降級**：`tile_status=unavailable`、`view_files` 退回原圖，由指南要求 agent 自行分段檢視）。已轉寫（`done`）、`not_table`、abandoned、檔案不存在、壞檔者不匯出。
  - `--import-transcription <results.json>`：嚴格驗證後匯入；**預設只預覽**（印將寫入筆數、略過筆數與每筆長度，**不印轉寫內容**），`--apply` 才寫。results.json 格式：`{"version":1,"model":"manual:<agent 名稱>","results":[{"image_id":int,"sha256":"<64 位小寫 hex>","is_table":bool,"text":str}]}`；欄位必須剛好如此（多餘或缺少一律拒收）。驗證：`model` 必須符合 `manual:[A-Za-z0-9-]{1,40}`；`image_id` 須存在於資料庫、不重複、所屬文章非 abandoned；`sha256` 須等於目前本機圖檔，且若 results.json 同資料夾有 `manifest.json`，也須在 manifest 內且一致；`text` ≤40000 字、不含控制字元（`\n`、Tab 可）、不含疑似金鑰／token／cookie／帳密鍵值（`investanchors_redact.secret_like`）；`is_table=true` 時 text 非空、`false` 時必須為空字串（記 `not_table`）。**任何一筆不合格即整批拒絕（exit 2，訊息只含序號／image_id／固定說明，不回顯內容）**。已 `done`／`not_table` 的圖預設**略過**（計入「略過」筆數），`--overwrite` 才覆寫。`--apply` 以單一交易寫入（`ArticleStore.apply_transcription_batch`，全有或全無），並在同一交易寫一筆 `alert_log` 稽核（`kind=manual_transcription_import`、key＝`<HHMMSS> written=N skipped=M model=manual:…`，只存數量；**刻意不寫 `import_runs`**，避免遮蔽排程「N 天無執行」健檢）。`--apply` 需資料庫已存在（不建庫）。
  - 互斥：兩旗標彼此不可併用，也不可與任何其他動作旗標併用（`--dry-run`、`--retranscribe`、`--transcribe-sample`、`--enable/--disable-transcription`、`--backfill-since`、`--resume`、`--force-weekly`、`--max-articles`、`--reset-abandoned` 等，一律 exit 2）；`--limit` 只能配 export，`--apply`／`--overwrite` 只能配 import。資料目錄防呆最先執行（正式庫無 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 即拒絕，export 也一樣）。
  - 與開關的關係：**不看也不改 `transcribe_enabled`**（見 quickstart §12）；`--retranscribe` 的換模型重轉**不會**覆寫 `transcribed_model` 以 `manual:` 開頭的列。顯示：`get_article` 對 `manual:` 轉寫標示「【圖片轉寫，手動（agent：<名稱>），可能有誤，請以原圖為準】」，API 轉寫維持「【機器轉寫，可能有誤，請以原圖為準】」；搜尋範圍與 API 轉寫相同（**2026-11-18 起兩者皆須通過驗證才納入搜尋，未驗證者在 `get_article` 改附未驗證警告，見下方「轉寫驗證等級」**）。
- **轉寫驗證等級（Phase 12，Q-028；詳見 quickstart §14）**——**零網路、零鑰匙圈、不登入、不取信、不通知**；資料目錄防呆最先執行：
  - `--import-verification <verification.json>`：嚴格驗證後匯入獨立檢核結果；**預設只預覽**（唯讀開庫，不建庫、不建表；只印數量與 image_id，**不印 issues 內容**），`--apply` 才寫（可寫連線，建立驗證表；單一交易，全有或全無；同交易寫一筆 `alert_log` 稽核，`kind=transcription_verification_import`、key＝`<HHMMSS> method=… ok=N flagged=M skipped=K`）。格式：`{"version":1,"verifier":"<英數連字號≤40>","method":"compare-d-c｜agent-spot-check｜arithmetic｜body-crosscheck","results":[{"image_id":int,"sha256":"<64 hex>","verdict":"ok｜issues","issues":[{"where":≤80字,"found":≤200字,"expected":≤200字（可選）,"kind":"truncated｜wrong-number｜missing｜extra｜other"}]}]}`；欄位必須剛好如此；`verdict=issues` 時 `issues` 必填（1～200 項）、`ok` 時不可帶；一次最多 200 張；`issues` 文字單行、拒收控制／bidi／零寬字元與疑似金鑰（`investanchors_redact.secret_like`）。對照資料庫：圖須存在、不重複、所屬文章非 abandoned、**已轉寫**（`untranscribed` 整批拒收）、sha256 等於目前圖檔，且同資料夾若有 `manifest.json` 也須一致。轉換規則：`ok`→`cross_checked`、`issues`→`flagged`；`reviewed` 不會由此寫入、`ok` 不動 `reviewed`、`flagged` 只有「method 不同於任何曾標過疑慮的來源」才可轉 `cross_checked`（防洗白）；`not_table` 圖只接受 `issues`（`ok` 略過）。`--apply` 以最新狀態重新判斷（預覽後狀態可能變了）。需資料庫已存在（不建庫）。
  - `--mark-reviewed <ids>`：PO 本人逐格核對後設為 `reviewed`（**唯一**會寫 reviewed 的路徑）；ids 為逗號分隔正整數、不重複、≤200、每張須已轉寫（`done`）；預設只預覽（印原狀態分布；含 flagged 時提醒），`--apply` 才寫（單一交易、同交易稽核 `kind=transcription_mark_reviewed`、key＝`<HHMMSS> reviewed=N flagged_before=M`）。
  - `--export-verification-task [--limit N] [--only-unverified]`：**唯讀**匯出 `<data-dir>/articles_probe/verify-task-<時間>/`：`manifest.json`（每項 `image_id`／`article_id`／`seq`／原圖絕對路徑 `path`／`sha256`／`width`／`height`／`is_long`／`transcription_path`／`line_count`／`transcribed_model`／`current_verification`／`tile_status`／`tiles`／`view_files`；**不含標題、內文與網址**）、`transcriptions/<image_id>.md`（每行前加 `[L001]` 行號）、`VERIFY_GUIDE.md`、長圖切片（同 `--export-untranscribed`，無瀏覽器時降級）。候選：已轉寫、有本機檔且可讀、文章非 abandoned、驗證等級非 reviewed（`--only-unverified` 時僅 unverified）；`--limit` 預設 10、1～100。庫不存在回 exit 1、不建庫；舊庫（沒有驗證表）照常匯出（全視為 unverified）。
  - 互斥：與方案 D 的兩個旗標彼此、以及與其他動作旗標皆不可併用（exit 2）；`--limit` 只配兩個 export、`--only-unverified` 只配 `--export-verification-task`、`--apply` 只配 `--import-transcription`／`--import-verification`／`--mark-reviewed`、`--overwrite` 只配 `--import-transcription`。
  - 顯示與搜尋：`search_articles` 只納入 `cross_checked`／`reviewed` 的轉寫文字；`get_article` 對 `unverified`／`flagged` 附「【未驗證／有疑慮的圖片轉寫：數字可能有誤，不得用於投資判斷，請對照原圖】」（flagged 另附疑慮摘要），`cross_checked`／`reviewed` 標示等級與方法。唯讀連接器遇到驗證表不存在＝全部 unverified。**重寫轉寫（`--overwrite`、`--retranscribe` 換模型、重新匯入）一律把該圖重置為 unverified 並清除疑慮記錄。**
  - `compare_transcriptions.py --emit-verification <路徑>`（見 quickstart §13／§14）：依比對結果輸出 verification.json（`method=compare-d-c`、`verifier=compare-transcriptions`）；不覆寫既有檔；比對失敗或未配對的圖不輸出。
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
  定義（2026-11-16 補）：**重複**＝不同 ID 但正規化網址相同，或標題＋清單日期相同；`not_fetched`（庫內有紀錄但尚未抓到內文）另列、不計缺漏；`older_not_deferred`（早於截止日卻未標延後）只列提示；進度檔 `<data-dir>/articles_probe/reconcile-state.json`（游標與已見 ID，不放 setting 表、不碰 `backfill_state`），截止日放寬或 `--restart` 即作廢重掃；**只有手動 CLI、無排程**。完全空白的清單頁（連置頂都沒有）視為讀取異常：不計入、進度不越過，報告註記 `blank_page`（不通知、不寫 DB）。

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

## 間隔下限防呆（低頻硬性要求）

- 頁／篇間隔下限 **30 秒**（`investanchors_limits.MIN_PAGE_DELAY_MS`＝scraper JS `MIN_DELAY_MS`）、圖片間隔下限 **5 秒**（`MIN_IMAGE_DELAY_SECONDS`／JS `MIN_IMAGE_DELAY_MS`）。低於下限的值一律**夾到下限**，不是拒絕；兩端（Python 與 JS）各自強制。
- Python：`Importer`／`Reconciler` 建構時夾 `delay_ms`；`article_images.download_images` 實際睡眠夾 ≥5 秒。JS：`investanchors_session.js` 的 `clampDelay()`，生效值寫在 summary 事件的 `effective_delay_ms`。
- **命令列沒有任何可調降間隔的旗標**（`investanchors_import.py`／`article_probe.py`／`article_reconcile.py`；測試以 parser 旗標斷言守住）。`Importer` 建構子的 `delay_ms` 注入僅供測試。
- 唯一繞過：環境變數 `INVESTANCHORS_TEST_ALLOW_SHORT_DELAY=1`，**僅測試用，正式環境（launchd plist、shell、CLI）不得設定**；測試端由 `tests/fake_investanchors_site.py` 與 `test_investanchors_import.py` 在 import 時設定並由 scraper 子行程繼承；plist 不含此變數（`test_investanchors_delay_floor.py` 斷言）。
