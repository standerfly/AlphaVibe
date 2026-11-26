# Tasks: Substack 文章抓取與儲存（011，第 1 包）

**Input**: `specs/011-substack-fetch-store/`（spec.md、plan.md、research.md R0～R11、data-model.md、contracts/cli.md、contracts/config-format.md、contracts/notifications.md、contracts/health-output.md、quickstart.md V1～V16）
**Prerequisites**: plan.md（Phase 0/1 完成、PO 2026-11-20 已決定 15 項中的 14 項；FR-013 暫解讀待 PO 確認，見 T067）
**Tests**: 本功能 spec／plan **明確要求**大量測試（FR-021 流水線隔離 T-A～T-E、FR-026 外洩掃描、FR-009 原子性與回滾、FR-017 假時鐘邊界、FR-004／FR-034 等）。每個故事都是「先寫測試（預期先失敗）→ 實作 → 跑測試轉綠」。守門型測試（靜態掃描）建立時即應為綠，會在任務中註明。
**Organization**: Setup → Foundational → US2 → US1 → US3 → US4 → US5 → US6 → US7 → Polish。**任務編號順序就是建議執行順序**（speckit-implement 依編號執行）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行（不同檔案、且無未完成的相依）
- **[US#]**：所屬 User Story（Setup／Foundational／Polish 不標）
- **【須 PO 當下確認】**：須 PO 在 Mac 上、在當下對話親自確認的真實執行（登入、鑰匙圈、消耗訂閱額度、安裝排程、對 Substack 的真實請求、正式環境部署；FR-020）。**agent 不得自行執行，別的對話的同意不算。**
- **【GATE】**：關卡任務（獨立驗收／審查）
- **編號**：T### 為連續編號；任務順序即建議執行順序。
- 路徑慣例（plan.md「Project Structure」）：程式 `poc/kb-mcp/substack_*.py`；測試 `poc/kb-mcp/tests/test_substack_*.py`＋`poc/kb-mcp/tests/_substack_fixture.py`；只修改 `poc/kb-mcp/backup_databases.py`、`poc/kb-mcp/check_scheduled_jobs.py`（及其兩個既有測試檔，只新增案例）；排程 `ops/launchd/com.alphavibe.substackimport.plist`；`.gitignore`、`CLAUDE.md`。

## 已決定事項（Claude 決定、PO 可改）

下列為文件間矛盾或空白，屬可逆的技術選擇，由 Claude 於 2026-11-20 決定並已同步到 spec 以外的各文件；PO 可隨時推翻：

1. **圖片下載失敗不算執行失敗**：依 spec US3-AS2「執行不算失敗」，`run.result='ok'`、exit 0；缺圖數顯示在 stdout 與摘要（`contracts/cli.md` 退出碼已改）。`exit 1`／`partial` 只對應作者失敗與預算中止。
2. `run.trigger` 列舉補上 `reclassify`（data-model §1.5）。
3. `transcription_trial.result` 移除 `refused`：被拒絕的手動轉寫執行（確認碼不符、跨日、選取不符、疑似排程啟動）**不寫試跑紀錄**，只回退出碼與訊息（research R1、`contracts/cli.md §3`）。
4. `dedupe_conflict`（guid 與 link_norm 各命中不同兩篇）計數**只印在 stdout 與日誌、不入庫**，不新增欄位。
5. `--reclassify` 給不存在的文章 id：明列錯誤並 **exit 1**（存在的 id 仍照常處理）；`--backfill` 對已停用或不存在的作者：拒絕並 **exit 2**（寫入 `contracts/cli.md`，T016／T018／T042／T043 驗收）。
6. plan.md 與 quickstart 的驗證項範圍統一為 V1～V16。
7. 工作位置：開發在獨立 worktree `/Users/stander/My_project/AlphaVibe-011`；主資料夾被別的 session 佔用、不得碰（通用規則 11）。
8. 健檢「歷史不足 7 天」的措辭改為「可比較天數 N，未滿 7 天，不判斷」，避免與 SC-010 禁字掃描（「不足」）自相矛盾。
9. **N 類（非文字）文章決定（PO 2026-11-25，spec Q14／FR-011／FR-035／SC-015；整理者解讀、待 PO 確認）**：PO 原話「同意你的建議，但也要提醒我N類要不要處理。」→ N 類 `body_text` 恆為 NULL、不進搜尋（`article_effective.effective_body_text` 對 N 恆 NULL），仍保留 `content_html`、圖片列與標題／作者／完整度；每篇 N 類逐篇通知附一次性固定提醒；**摘要不附提醒句、仍列非文字篇數（PO 2026-11-25 決定，spec Q15，原解讀已修正）**；系統不自行處理 N 類。N→F／P 重判的內文存在 `reclassification.derived_body_text`（不動 `article` 欄位）。本次未新增任務、未重新編號，而是擴充 T005／T006（schema 與視圖）、T014／T015（分類與存放）、T016／T017（重判）、T020／T023／T024（通知與主流程）、T054（健檢確認不新增 N 類異常提醒）。

## 通用規則（每個任務都適用）

1. **Python 3.9.6、只用標準庫**（`/usr/bin/python3`）：不得用 `X | Y` 型別、`match`、3.10+ API；不新增任何套件（plan Technical Context）。
2. **測試一律用獨立資料目錄**：`tempfile` 目錄（經 `os.path.realpath`）或 `poc/data-test-substack/`；任何 CLI 第一步都經 `article_data_guard.resolve_data_dir()`（`poc/kb-mcp/article_data_guard.py:21-33`）；**絕不**對 `poc/data/`（正式庫）跑測試。
3. **路徑比較一律 `os.path.realpath`**（macOS `/var`→`/private/var`，CLAUDE.md 2026-11-16 已踩兩次）：資料目錄、鎖檔、圖片路徑「在資料目錄底下」的檢查、T-C 的 `articles.db` 攔截判斷。
4. **不改 010**：`article_store.py`、`transcription_pipeline.py`、`investanchors_*.py`、`claude_cli_runner.py`、`notify.py`、`article_data_guard.py`、`investanchors_redact.py`、`rotate_logs.py`、`ops/deploy.sh` 只 import 不修改（research R0）。
5. **日誌／stdout／stderr／`last_error_code`／`poll_log` 不含標題、內文、文章網址（slug 等同標題）、圖片網址、token、notify 錯誤原文**（FR-026；research R4、R6）。通知是唯一可含標題的輸出，且不含文章連結（FR-025、FR-027 例外）。
6. **sqlite3 一律 `isolation_level=None`＋`with store.transaction():`（顯式 `BEGIN IMMEDIATE`）**；交易外不得有任何 DML（research R8）。
7. **建構子不得有寫資料的副作用**（CLAUDE.md 2026-08-22）：`SubstackStore.__init__` 只建表；設定檔 `init` 是明確子命令。
8. **bytecode 快取坑**（CLAUDE.md 2026-09-03）：「改了程式但行為／測試結果與檔案內容矛盾」時，先跑 `python3 -c "import sys; sys.path.insert(0,'poc/kb-mcp'); import <模組> as m; print(m.__cached__)"`，必要時刪 `~/Library/Caches/com.apple.python/<專案路徑>/` 下對應 `.pyc`；不要先懷疑程式或重寫。最終驗收以 `git archive` 乾淨副本跑（T064）。
9. **子行程環境白名單須含 `USER` 與 `LOGNAME`**（`claude_cli_runner.py:61` 的 `ENV_ALLOW`；缺了 claude 訂閱登入偵測會 loggedIn=False）：手動轉寫一律走 `ClaudeCli` 既有白名單、不自造環境；排程本身不開子行程（FR-019）。
10. **每個任務完成的證據**＝該任務指定的測試實跑結果（指令＋最後幾行輸出）。全套回歸以 T002 記錄的基線比對，不得新增失敗（FR-031、SC-004）。
11. **工作位置**：本功能一律在開發用獨立 worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`；主資料夾可能被其他 session 切到別的分支，不要假設其分支）內開發與測試；主資料夾 `/Users/stander/My_project/AlphaVibe` 被別的 session 佔用，不得碰、不得切換任何分支、不得在那裡 commit／推送。換環境或隔一段時間接手：先 `pwd`、`git status`、`git branch --show-current`（必須是 `011-substack-fetch-store`）、`git diff --stat`（CLAUDE.md 2026-08-09）。不切換分支。涉及正式環境的路徑（`AlphaVibe-prod`）不變。
12. **T-A 禁字**：`poc/kb-mcp/substack_*.py` 全文（含註解、docstring、字串）不得出現 `articles.db`、`article_store`、`ArticleStore` 字樣（T-A 靜態測試掃全文，連註解也算）；要提到 010 的文章庫時寫「010 文章庫」。

---

## Phase 1: Setup

**Purpose**: 基線、忽略規則、共用測試夾具

- [x] T001 確認工作環境：在開發用獨立 worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`；主資料夾可能被其他 session 切到別的分支，不要假設其分支）執行 `pwd`、`git branch --show-current`（須為 `011-substack-fetch-store`）、`git status --short`（須乾淨或只有本功能異動）、`/usr/bin/python3 --version`（須 3.9.6）；有未預期異動先查清楚來源再動手，不清除、不切分支（CLAUDE.md 2026-08-09 教訓）
- [x] T002 **FR-031／SC-004 改動前基線**：在開發用獨立 worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`；主資料夾可能被其他 session 切到別的分支，不要假設其分支）跑 `python3 -m unittest discover -s poc/kb-mcp/tests 2>&1 | tail -n 40`，另各跑一次 `python3 -m unittest poc/kb-mcp/tests/test_backup_databases.py`、`python3 -m unittest poc/kb-mcp/tests/test_check_scheduled_jobs.py`（以 `-s poc/kb-mcp/tests -p 'test_backup_databases.py'` 形式），把「總數、失敗／錯誤的測試名稱」附記在本任務行尾（例：`基線：N tests, failures=[…]`）；010 tasks 記載的既有無關失敗（`test_us_stock_price_client.GetQuoteFallbackTest`、`test_flight_search.SampleDatesTest.test_covers_requested_number_of_months`）若仍存在照實記錄。另記 `ls ops/launchd/` 清單，供 T049（T-D）與 T074 比對（基線 2026-11-25 實跑：全套 `python3 -m unittest discover -s poc/kb-mcp/tests` → Ran 2340, failures=9, errors=4, skipped=59；既有無關失敗＝test_us_stock_price_client.GetQuoteFallbackTest ×4（error）、test_article_manual_transcribe.ExportTest.test_output_folder_location_and_name、test_flight_search.SampleDatesTest.test_covers_requested_number_of_months、test_investanchors_delay_floor.JsClampTest ×4、test_transcription_pipeline.GuardTest.test_argv_has_no_billing_flags_and_fixed_safe_shape、test_transcription_pipeline.HappyPathTest ×2；`-p 'test_backup_databases.py'` → Ran 11 OK；`-p 'test_check_scheduled_jobs.py'` → Ran 59, errors=3（WebServiceCheckTest ×3，需本機 8080 服務）；`ls ops/launchd/` ＝ com.alphavibe.{amoscheck,flighttracking,investanchorsimport,statementimport,transcriptionpipeline}.plist 五個，尚無 substackimport）
- [x] T003 [P] 在 `.gitignore` 新增一行 `poc/data-test-substack/`（附一行註解：011 手動測試用獨立資料目錄，絕不指向 `poc/data`）；驗收：`git check-ignore -v poc/data-test-substack/x` 有命中、`git check-ignore -v poc/data/x` 仍命中（FR-027 可驗證項 1）
- [x] T004 [P] 建立共用夾具 `poc/kb-mcp/tests/_substack_fixture.py`（**純合成內容，不複製任何真實文章文字**）：(a) `make_feed(items)` 產生 RSS 2.0（`guid isPermaLink=false`、`link`、`title`、`pubDate`、`content:encoded`、`description`、`enclosure`）；(b) 結構樣本（依 research R6 與 `docs/spec-intake/substack-import/raw/2026-11-19-paid-preview-analysis.md` 第 4 行描述的結構）：Read more 尾端預覽、純播放器、嵌入卡片、長文（≥15,000 字）帶 Read more 尾端、短文無尾端、免責聲明結尾、`content:encoded` 缺漏、尾端有 Read more 文字但 href 主機不符、Read more 後面還有內容、含 `<!DOCTYPE`／`<!ENTITY` 的惡意 XML、HTML 挑戰頁；(c) `FakeHttp`：依 URL 回傳腳本化回應（200／304／403／429／HTML 挑戰頁／逾時／網路錯誤／卡住直到逾時／轉址／超大回應），記錄每筆請求的 URL 與 headers；(d) `FakeClock`：可設定台北時間（`+08:00`）與 monotonic、`sleep()` 只記錄不真睡；(e) `FakeNotifier`：記錄每則文字、可腳本化失敗並回傳含假 Bot token（`123456789:` 後接 35 字元）的錯誤字串；(f) `FakeClaudeRunner`；(g) `temp_data_dir()`：`tempfile.mkdtemp()` 經 `os.path.realpath`；(h) `write_config(data_dir, **overrides)`；(i) 外洩掃描常數 `TITLE_MARK`、`BODY_MARK`、`SLUG_MARK`、`IMG_URL_MARK`。驗收：`python3 -c "import sys; sys.path[:0]=['poc/kb-mcp','poc/kb-mcp/tests']; import _substack_fixture"` 無錯；檔內不得出現任何 `urlopen` 真實呼叫

---

## Phase 2: Foundational（阻擋所有故事）

**Purpose**: `substack.db` schema 與交易、設定檔載入／驗證／原子寫入、HTTP 與 robots、回應判別、執行鎖與 CLI 骨架、資料目錄防呆、隔離與 FR-027 守門

**⚠️ CRITICAL**: 本階段完成前不得開始任何 User Story

- [x] T005 [P] 先寫 `poc/kb-mcp/tests/test_substack_store.py`（**預期先失敗**：`substack_store` 尚不存在）：(1) 建表後存在 data-model §1 全部表 `author`、`article`、`article_image`、`poll_log`、`run`、`robots_cache`、`transcription_trial`、`image_transcription`、`reclassification` 與唯讀視圖 `article_effective`（輸出欄含 `effective_body_text`；`reclassification` 含 `derived_body_text` 欄，FR-011、Q14），以及 §1.2／§1.9 列出的索引（`UNIQUE(guid) WHERE guid IS NOT NULL`、`UNIQUE(link_norm)`、`(author_key, published_at)`、`(fetched_at)`、`UNIQUE(article_id, seq)`、`UNIQUE(image_id, trial_id)`、`(article_id, id)`）；(2) **建構子不寫任何資料列**（建構後所有表 `COUNT(*)=0`）；(3) 連線 `isolation_level is None`、`check_same_thread=False`、`busy_timeout=5000`、非 WAL；(4) `transaction()`：成功 COMMIT、例外 ROLLBACK 後重拋、交易外 `conn.in_transaction is False`、交易內為 True；(5) **FR-009 回滾測試（research R8 必列）**：(a) 文章列寫入後、圖片列寫入前注入例外 → `article` 與 `article_image` 皆無該篇；(b) COMMIT 前注入例外 → 同上；(c) 假 `sqlite3.OperationalError('database or disk is full')` → 回滾並轉成 `DiskFullError`；(6) 去重：`guid` 相同或 `link_norm` 相同皆回 None 不寫、不覆寫；guid 命中 A、link_norm 命中 B 時視為重複、`find_duplicate` 回傳值區分 `duplicate`／`dedupe_conflict`（**只是回傳值，不入庫**：`PRAGMA table_info` 斷言 `run`／`poll_log`／`article` 沒有任何 dedupe 計數欄位）；(7) 靜態守門：讀 `substack_store.py` 原始碼，`UPDATE article SET` 只允許出現 `notify_status`／`notify_attempts`／`notified_at` 欄位（FR-007 不覆寫）、`reclassification` 無 UPDATE／DELETE（FR-033）；(8) `open_readonly(data_dir)` 用 `mode=ro`、庫不存在丟 `FileNotFoundError` 且**不建檔**、開啟前後檔案位元組不變；(9) `space_status(data_dir)` 回傳剩餘 GB（`shutil.disk_usage`）、`substack.db` MB、`substack_images/` 實際目錄 MB，`format_space_line()` 輸出 `空間：剩餘 X GB；substack.db Y MB；圖片 Z MB`，計算失敗輸出 `空間：無法取得`（FR-028、research R4）；(10) 時間欄位帶 `+08:00`
- [x] T006 實作 `poc/kb-mcp/substack_store.py`：`DB_FILENAME="substack.db"`、固定 `UTC+8` 常數（比照 010 寫法）、`class SubstackStore(data_dir)`（`sqlite3.connect(..., isolation_level=None, check_same_thread=False)`、`PRAGMA busy_timeout=5000`、DDL 在自己的顯式交易內）、`transaction()` context manager、`insert_article_with_images(article_dict, images)`（單一交易，回傳 id 或 None）、`find_duplicate(guid, link_norm)`、作者狀態讀寫、`start_run/finish_run`、`add_poll_log`、圖片狀態查詢與更新、通知佇列查詢與更新、`robots_cache` 讀寫、`reclassification` INSERT 與歷史查詢、`article_effective` 查詢（含 `effective_body_text`：有效完整度 N → NULL；否則 `article.body_text`，缺則取最近一筆非 NULL 的 `derived_body_text`）、`reclassification` INSERT 支援 `derived_body_text`、狀態與健檢用統計、`classmethod open_readonly`（比照 `article_store.py:473-485` 的 `mode=ro`，但**不 import `article_store`**）、模組函式 `space_status()`／`format_space_line()`；日後加欄位的寫法比照 `article_store.py:285-309`（本包新庫無遷移）。**註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣**（T-A 掃全文，連註解也算；寫註解時用「010 文章庫」）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_store.py'` 全綠
- [x] T007 [P] 先寫 `poc/kb-mcp/tests/test_substack_config.py` 的載入／驗證／寫入部分（**預期先失敗**）：逐條覆蓋 `contracts/config-format.md` 驗證表——`version` 必須 1；`min_poll_interval_minutes` 10～1440（9 與 1441 拒絕）；`alert_policy` 只收 `every_failure`／`consecutive_3`；`image_hosts` 0～20 個、小寫主機名、含路徑／埠／IP 拒絕；`authors` 1～20、`key` 不重複且符合 `^[a-z0-9][a-z0-9-]{1,39}$`、`feed_url` 不重複；`name` 1～60 字；`feed_url` 須 `https://`、無帳密、無埠、無 query／fragment、路徑恰為 `/feed`、主機非 IP／`localhost`，`/feed/private` 拒絕（FR-001）；`enabled` 須 bool；未列出欄位拒絕；檔案不存在丟 `ConfigMissing`（無隱性預設值）；`init` 產生內容與契約「初始內容」逐欄相同、已存在則 exit 2 不覆寫；寫入走暫存檔＋`os.replace`（模擬寫到一半例外，舊檔位元組不變）；寫前備份 `substack_config.json.bak-YYYYmmdd-HHMMSS` 且只保留最新 10 份；`show` 印全文、`validate` 只印 OK 或原因；**正式目錄防呆**：以注入 env 呼叫且 realpath 等於 `article_data_guard.PRODUCTION_DATA_DIR`、未設 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` → exit 2 且未建立任何檔案
- [x] T008 實作 `poc/kb-mcp/substack_config.py` 的共用部分：`load_config(data_dir)`（讀取＋完整驗證，回傳 dict 或丟 `ConfigMissing`／`ConfigInvalid(原因清單)`）、`validate(cfg) -> list`、`write_config(data_dir, cfg)`（驗證→備份→暫存檔→`os.replace`）、`allowed_image_hosts(cfg)`（`image_hosts`＋各作者 feed 主機）、`main(argv, env=None, out=None)` 先 `resolve_data_dir()`，子命令 `init`／`show`／`validate`（其餘子命令在 US3／US4／US5 加入）；腳本自行把 `poc/kb-mcp/` 加進 `sys.path`。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_config.py'` 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T009 [P] 先寫 `poc/kb-mcp/tests/test_substack_feed.py`（**預期先失敗**）：(1) 請求：User-Agent 恰為 `Mozilla/5.0 (compatible; personal-feed-reader/1.0)`；有 etag 時帶 `If-None-Match`（原字串含 `W/`）；**不得**有 `Cookie`／`Authorization` header（FR-001）；逾時取 `min(30, 剩餘預算秒數)`；(2) 回應判別（data-model §2.4）：200＋XML→`ok_200`；304→`not_modified`；403→`blocked_403`；429→`rate_limited_429`；200 但 `Content-Type: text/html` 或內容以 `<!DOCTYPE html`／`<html` 開頭→`challenge_html`；其他狀態→`http_<碼>`；逾時→`timeout`；連線錯誤→`network`；>5MB→`too_large`；轉址到非該作者 feed 主機且非 `<x>.substack.com`→`redirect_refused`；(3) 解析：含 `<!DOCTYPE`／`<!ENTITY` 先拒絕→`parse_error`；壞 XML→`parse_error`；正常條目取出 guid、link、title、pubDate（`email.utils` 解析，失敗回 None）、content:encoded、description、enclosure 型別與網址；(4) `normalize_link()`：https、小寫主機、去 query／fragment、去尾斜線；(5) robots（`urllib.robotparser`）：快取在 `robots_cache` 24 小時；取 robots 失敗時用 7 天內快取，否則 `robots_unavailable`；禁止→`robots_disallow`；robots 請求不計入 feed 請求數；(6) `error_code(exc)` 只回代碼字串，**不含例外原文**（以含假 token 與網址的例外驗證）
- [x] T010 實作 `poc/kb-mcp/substack_feed.py`：可注入的 `fetch(url, headers, timeout)` 介面（預設以 `urllib.request` 實作、不跟隨未允許的轉址）、`build_headers(etag)`、`classify_response(status, headers, body)`、`parse_feed(body) -> items`（`xml.etree.ElementTree`，先拒 DTD）、`normalize_link()`、`RobotsGate(store, fetch, clock)`、`error_code(exc)`；常數 `UA`、`FEED_TIMEOUT=30`、`MAX_FEED_BYTES=5*1024*1024`；轉址拒絕規則參考 `article_images.py:26-31` 的寫法（另寫，不 import）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_feed.py'` 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T011 [P] 先寫 `poc/kb-mcp/tests/test_substack_import.py` 的骨架部分（**預期先失敗**）：(1) 未給 `--data-dir` → exit 2；指向正式目錄（注入 env、無 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`）→ exit 2，且資料目錄內未建立任何檔案（防呆先於讀設定、開庫、發請求）；(2) **V5／FR-017 忙碌**：測試先以 `fcntl.flock` 持有 `<data_dir>/.substack_import.lock` 再執行 → exit 3、stdout 含「忙碌」、`substack.db` 不存在者不被建立、已存在者位元組不變、FakeHttp 零請求；(3) 互斥選項（如 `--backfill` 與 `--reclassify` 同時給）→ exit 2；(4) 退出碼常數 0～5 與 `contracts/cli.md` 共通規則一致；(5) 鎖在任何例外路徑後都被釋放（之後可再取得）
- [x] T012 實作 `poc/kb-mcp/substack_import.py` 骨架：`run(argv, *, http=None, notifier=None, clock=None, sleep=None, env=None, out=None, err=None)` 依賴注入（比照 `investanchors_import.py:1058-1066` 的 `run(argv, **deps)` 慣例）、`argparse` 宣告 `contracts/cli.md §1` 全部選項（無動作／`--scheduled`／`--dry-run`／`--backfill`／`--retry-images`／`--reclassify` 搭 `--article-ids`|`--author`／`--reclassify-history`／`--status`）、第一步 `article_data_guard.resolve_data_dir()`、執行鎖 `fcntl.flock(LOCK_EX|LOCK_NB)`（比照 `transcription_pipeline.py:605-610`）、`finally` 釋放、退出碼常數；尚未實作的動作回 exit 2 並印代碼 `not_implemented`；`if __name__ == "__main__": sys.exit(run(sys.argv[1:]))`；自行加 `poc/kb-mcp/` 進 `sys.path`。驗收：T011 測試全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T013 [P] 建立 `poc/kb-mcp/tests/test_substack_isolation.py` 的守門部分（**守門型：建立時即應為綠，之後每階段都須保持綠**）：(1) **T-A 靜態（FR-006）**：讀所有 `poc/kb-mcp/substack_*.py`（不含 `tests/`）**全文，連註解、docstring、字串都算**，不得出現 `articles.db`、`article_store`、`ArticleStore` 任何字樣（含 `articles.db-journal` 等子字串），也不得出現 `article_store.py` 中 `def set_`／`def insert_`／`def update_`／`def mark_` 開頭的方法名（動態取得清單；**以完整識別字比對，不得用子字串比對**，以免誤傷 011 自己的 `insert_article_with_images` 等名稱）；掃描器自身要有反向測試（臨時檔只在註解寫 `articles.db` 也必須被抓到）；`poc/kb-mcp/transcription_pipeline.py`、`article_store.py`、`investanchors_import.py` 不得出現 `substack`；(2) **FR-019 靜態**：`substack_import.py`、`substack_feed.py`、`substack_html.py`、`substack_images.py`、`substack_store.py`、`substack_config.py`、`substack_reclassify.py` 不得 import `claude_cli_runner`、`article_transcribe`、`transcription_pipeline`、`subprocess`、`keychain_secrets`；(3) **FR-027 可驗證項**（plan.md）：`.gitignore` 含 `poc/data/` 與 `poc/data-test-substack/`；`app/` 下所有檔案、`poc/kb-mcp/server.py`、`server_readonly.py`、`us_stock_mcp_server.py` 不含 `substack` 字樣；`backup_databases.py` 的預設備份目的地在 `os.path.expanduser("~")` 底下。（檔案尚未存在者跳過該檔，不視為失敗）

**Checkpoint**（2026-11-25 實跑）: `python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_*.py'` → Ran 141 OK；全套 → Ran 2481, failures=9, errors=4（與 T002 基線同名同數，無新增失敗）

---

## Phase 3: User Story 2 — 付費文章只存預覽並清楚標示（Priority: P1）

**順序說明**：US2 排在 US1 之前，因為 `article.completeness` 為 NOT NULL，US1 存文章時必須呼叫 US2 的分類函式；US2 的重判只需 Foundational 的 `SubstackStore` 就能用直接插入的文章測試，不依賴 US1 的抓取。

**Goal**: 每篇判為 P／F／N（不確定一律 P、不看長度），HTML→純文字保留圖位標記；PO 可對指定文章／作者重判，歷史不覆寫。

**Independent Test**: 以夾具的結構樣本逐篇檢查分類（含長文帶 Read more 反例、純播放器）；直接以 `SubstackStore` 插入文章後執行 `--reclassify`，確認原判斷與原始內容位元組不變、`reclassification` 逐次新增、`article_effective` 取最近一筆、零網路零模型。

- [x] T014 [P] [US2] 先寫 `poc/kb-mcp/tests/test_substack_classify.py`（**預期先失敗**；V2、SC-006、FR-010～FR-012、FR-014）：(1) `html_to_text`：區塊元素換行、`li`→「• 」、`script`／`style` 丟棄、`iframe`／`audio`／`video` 與播放器 div→〔嵌入內容〕／〔播放器〕、`<img>`→`〔圖 N｜圖說：…｜alt：…〕` 依出現順序編號、`figure` 內 `figcaption` 併入標記不重複輸出、回傳圖片清單（seq、src、alt、caption）；(2) `classify(content_html, link)`：最後一個頂層區塊為 `<p>`、唯一有意義子節點為 `<a>`、文字正規化後等於 `Read more`（不分大小寫）、href 為 `https://<文章連結主機>/p/<slug>` → `P`／`read_more_tail`；無尾端且可見文字（扣除圖位與播放器標記、空白）≥200 字 → `F`／`text_ge_200`；<200 字 → `N`／`text_lt_200`；**邊界 199／200 字**；(3) 不確定一律 `P` 且 `uncertain:<代碼>`：`content:encoded` 缺漏或空、HTML 無法解析、有 Read more 文字但結構或 href 主機不符、Read more 後面還有內容（FR-012）；(4) **不以長度判斷**：同一 Read more 尾端配 50 字與 15,000 字皆為 P；15,000 字無尾端為 F、50 字無尾端為 N（不是 P）；(5) P 類 `body_text` 不含尾端 Read more 段；(6) 不變式：reason 以 `uncertain:` 開頭 ⇒ completeness 為 P；P 只來自 `read_more_tail` 或 `uncertain:*`（data-model §3）；(7) `RULE_VERSION` 為非空字串常數、`MIN_FULLTEXT_CHARS == 200`；(8) **FR-011 存放斷言**（以 `SubstackStore.insert_article_with_images` 實際寫入再讀回）：F 類 `body_text` 存全文（等於 `html_to_text` 對整份內容的結果，字數與來源可見文字一致、無截斷）；P 類 `body_text` 只存公開預覽（尾端 Read more 段已移除、不含 Read more 之後的任何內容）且 `completeness='P'` 可被讀出作為「僅預覽」標示；N 類 `completeness='N'`、可見文字 <200 字，**`body_text` 必為 NULL／空（FR-011、Q14；不保存零碎文字）**，但 `content_html` 原樣保存、圖位標記以 `article_image` 列（seq、圖說、alt）保存；`article_effective.effective_body_text` 對 N 為 NULL（不進搜尋可見範圍）；通知與健檢一律標「非文字」；F／P 的 `body_text` 非 NULL；三類的 `content_html` 皆原樣保存；(9) 不變式：`completeness='N'` ⇔ `body_text IS NULL`
- [x] T015 [US2] 實作 `poc/kb-mcp/substack_html.py`（只用 `html.parser`）：`html_to_text(html) -> (body_text, images)`、`visible_text_len(text)`、`classify(content_html, link) -> (completeness, reason)`、常數 `MIN_FULLTEXT_CHARS=200`、`RULE_VERSION`（例 `"2026-11-20.1"`）與 reason 代碼（FR-010～FR-012、FR-014、research R6）。`html_to_text` 對 N 類只用於取得圖位清單（寫入 `article_image`），其文字輸出不得寫入 `article.body_text`（FR-011、Q14）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_classify.py'` 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T016 [P] [US2] 先寫 `poc/kb-mcp/tests/test_substack_reclassify.py`（**預期先失敗**；V12、SC-012、FR-033）：以 `SubstackStore.insert_article_with_images` 直接插入 2 位作者的文章；(1) `--reclassify --article-ids` 與 `--reclassify --author` 各執行，每篇新增一列 `reclassification`（結果相同也記一列，`changed=0`），`old_completeness`＝當下有效值，`rule_version`＝`substack_html.RULE_VERSION`、`trigger` 為 `po_article`／`po_author`；(2) 重判兩次 → 2 列、`id` 順序正確、`article_effective.effective_completeness` 取最近一列、`original_completeness` 保留原判斷、`reclassified_count=2`；(3) 重判前後 `SELECT * FROM article` 每欄位元組完全相同（含 `content_html`、`body_text`、`completeness`、`classify_reason`）；(4) 執行期攔截 `urllib.request.urlopen`、`socket.create_connection`、`subprocess.Popen`／`subprocess.run` → 0 次；FakeNotifier 0 則；(5) `--dry-run` 不寫庫（`substack.db` 位元組不變）、只列會改變的 id 與新舊類別；(6) 不存在的 id 明列錯誤於 stdout 且整體 **exit 1**（存在的 id 仍照常重判並寫入；全部不存在也 exit 1、不新增任何 `reclassification` 列；已決定事項 #5）；(7) `--author` 只含該作者文章；(8) 鎖被占用 → exit 3 且 0 列新增；(9) 寫一列 `run`（`trigger='reclassify'`）；(10) `--reclassify-history` 唯讀列出原判斷與全部重判（時間、前後類別、依據、規則版本），庫位元組不變；(11) stdout 不含標題（以 `TITLE_MARK` 斷言）；(12) **N 類重判（FR-011、FR-033、Q14、SC-015(f)）**：原判斷 N 的文章（`body_text` 為 NULL）重判為 F → 新增的 `reclassification.derived_body_text` 等於 `html_to_text(content_html)`、`article_effective.effective_body_text` 非 NULL、重判前後 `article` 所有欄位位元組不變（`body_text` 仍為 NULL）、站方請求與模型呼叫 0 次、通知 0 則（不產生新的 N 類提醒）；再次重判回 N → `effective_body_text` 為 NULL、舊列 `derived_body_text` 保留；重判結果仍為 N → `derived_body_text` 為 NULL；原判斷 F 的文章重判為 N → `effective_body_text` 為 NULL
- [x] T017 [US2] 實作 `poc/kb-mcp/substack_reclassify.py`：`reclassify(store, *, article_ids=None, author=None, dry_run=False, trigger, run_id, clock) -> report`（呼叫與匯入同一個 `substack_html.classify`；只讀 `content_html`；`body_text` 不重算；**原判斷 N 而新結果為 F／P 時，以 `html_to_text(content_html)` 產生 `derived_body_text` 隨新增列寫入**，其餘情況為 NULL；FR-011、Q14）、`history(store, ids)`、`effective_completeness(store, id)`（research R11）。驗收：T016 中直接呼叫模組函式的案例轉綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T018 [US2] 在 `poc/kb-mcp/substack_import.py` 接上 `--reclassify`（`--article-ids` 逗號分隔／`--author`）、`--dry-run` 組合與 `--reclassify-history`：取鎖、寫 `run`（`trigger='reclassify'`）、不建立 http／notifier、輸出「檢查 N 篇、未變 N 篇、改變 N 篇（例 P→F ×2）」；找不到的 id 明列錯誤並使整體 exit 1（已決定事項 #5）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_reclassify.py'` 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）

**Checkpoint**（2026-11-25 實跑）: US2 Independent Test 通過（test_substack_reclassify.py 18 項全綠，含 N→F 的 derived_body_text 與零網路／零模型攔截）；`test_substack_*.py` → Ran 141 OK

---

## Phase 4: User Story 1 — 每日自動收到追蹤作者的新文章（Priority: P1）🎯 MVP

**Goal**: 22:00（錯過 01:00 補跑）讀設定 → 每作者至多一次條件請求 → 14 天窗 → 去重 → 分類 → 逐篇交易存入 → 逐篇通知（無連結）＋事件摘要；排程零模型、零登入；同排程日只執行一次；20 分鐘牆鐘預算。

**Independent Test**: 空庫＋2 位作者執行一次只存 14 天內文章；再執行一次篇數不變；某作者新增文章後下一次執行存入並發通知；假時鐘邊界逐一通過。

- [x] T019 [US1] 先在 `poc/kb-mcp/tests/test_substack_import.py` 寫主流程測試（**預期先失敗**；V1、SC-002、FR-001、FR-003、FR-007、FR-008、FR-019）：(1) 2 位作者、假 feed 各 20 篇跨 3 個月 → 只存 `published_at ≥ window_from`（`activated_at` 台北日期往前 14 天 00:00）者；(2) 立即再跑一次 → 文章總數不變、無重複；(3) 每作者每次執行 feed 請求 ≤1（FakeHttp 依 feed URL 計數）、作者之間 `sleep(5)`、robots 先於 feed；(4) 第二次帶 `If-None-Match`；304 → 不解析、不寫文章、`last_request_at` 更新、`consecutive_failures` 歸零；(5) pubDate 解析不了 → 不存、`skipped_no_pubdate` 計數；guid 或 link_norm 重複 → 略過；guid 與 link_norm 各命中不同兩篇 → 略過並計 `dedupe_conflict`，該計數**只印在 stdout 與日誌、不入庫**（`run`／`poll_log` 無對應欄位；已決定事項 #4）；(6) 文章欄位：`source='schedule'`（`--scheduled`）或 `manual`、`completeness`／`classify_reason` 來自 `substack_html.classify`、`content_html` 原樣、圖片列以 `pending` 與文章同交易建立；(7) 20 篇全為新文 → `poll_log.all_new=1`；(8) 請求不含 `Cookie`／`Authorization`；(9) **FR-019 執行期**：攔截 `subprocess.Popen`／`subprocess.run` 為 0 次，且執行後 `sys.modules` 不含 `claude_cli_runner`；(10) 首次看到啟用作者時寫入 `activated_at`／`window_from`／`last_seen_enabled=1`；(11) 無新文章時 stdout 有「無新文章」且不發通知（US1-AS4）
- [x] T020 [US1] 在 `poc/kb-mcp/tests/test_substack_import.py` 寫通知測試（**預期先失敗**；V14、SC-014、FR-025、FR-027）：(1) 每篇一則，文字恰為 `contracts/notifications.md §1` 格式（`📰 Substack 新文章｜{出版名稱}`／標題／`完整度：全文|僅預覽|非文字`），F→全文、P（含 uncertain）→僅預覽、N→非文字；依發布時間由舊到新；(2) 通知文字不含 `http://`、`https://`，也不含該文章實際的 `link`／`link_norm` 值（不以「link」子字串判斷）；(3) 節流：相鄰兩則之間 `sleep(1.5)`；(4) 發送失敗 → 該篇 `notify_status='failed'`、`notify_attempts+1`、同次不重試；下次執行**先**補發 `pending`／`failed` 再發新文章；累計 3 次 → `abandoned`；文章存檔不受影響（先寫庫後通知）；(5) 本次有新文章／告警／漏文提示時最後發 1 則摘要，格式依 `contracts/notifications.md §2`，含 `format_space_line()` 的空間行；**摘要的「圖片：本次下載 d 張、缺圖待補 m 張、放棄累計 a 張」行在本任務階段圖片計數尚未實作（T031／T032 才有），先固定填 0（`本次下載 0 張、缺圖待補 0 張、放棄累計 0 張`），只驗格式；實值由 T031／T032 驗證**；漏文提示行與「尚未通知成功」行在條件成立時出現；逐篇通知不含空間行（FR-028）；(6) FakeNotifier 回傳含假 Bot token 的錯誤 → stdout／stderr 只出現「失敗 N 則」，不含 token 或錯誤原文（research R4）；(7) **N 類提醒（FR-035、SC-015(b)(c)(d)(e)、US1-AS7、US2-AS9）**：夾具含 N 類（<200 字純播放器）文章時，其逐篇通知恰為 `contracts/notifications.md §1` 的四行格式（含固定提醒句「⚠️ 此文為非文字、內文未保存，請決定是否要處理。」），不含 `http://`／`https://`、不含該文章實際 link 與任何內文片段；F／P 類通知**不含**該句；摘要在非文字篇數 >0 時**不含**提醒句（逐字斷言不含 `NON_TEXT_REMINDER`），仍列非文字篇數（PO 決定 Q15）；同一篇 N 類文章再跑一次（及補發、`--reclassify`）後 FakeNotifier 收到的該篇提醒累計 1 次（通知失敗補發重送同一則、成功後累計 1 次）；N 類文章匯入全程 FakeHttp 除 feed／白名單圖片外零請求、FakeClaudeRunner／`subprocess` 0 次（系統不自行處理 N 類）
- [x] T021 [US1] 在 `poc/kb-mcp/tests/test_substack_import.py` 寫排程日與預算測試（**預期先失敗**；V10、V15、FR-017、FR-018、SC-014）：以 FakeClock 帶 `--scheduled`：(1) **21:59**：屬前一排程日——前一日未實際執行 → 以 `catchup` 執行；已執行 → `already_done` 零網路；(2) **22:00** → 新排程日、`trigger='schedule'` 執行；(3) **23:00**、**23:59**、**00:59** → `deferred`、零網路、只寫一列 `run`；(4) **01:00**：當日未執行 → `catchup` 執行；已執行 → `already_done`；(5) 序列「22:00 執行 → 23:30 `deferred` → 01:00 `already_done`」；(6) 序列「22:00 錯過 → 23:30 `deferred` → 01:00 執行」（`deferred`／`already_done` 列不得讓補跑誤判，判斷只看 `trigger IN ('schedule','catchup') AND result NOT IN ('deferred','already_done')`）；(7) 07:00 醒來且當日未執行 → 立即執行（不受 05:00～18:00 時窗限制，FR-018）；(8) 不帶 `--scheduled` 的手動執行不做排程日判斷；(9) `schedule_day`＝啟動時刻減 22 小時的日期；(10) **牆鐘預算**：FakeHttp 卡住、FakeClock monotonic 前進 → 20 分鐘時強制中止，`run.result='aborted_budget'`、`budget_exhausted=1`、exit 1、鎖已釋放（測試立即再取鎖成功）、未發通知者仍為 `pending`、無半寫入文章；每次網路逾時取 `min(原逾時, 剩餘時間)`
- [x] T022 [US1] 在 `poc/kb-mcp/substack_import.py` 實作主流程前半「同步作者與首次窗口」（`contracts/cli.md §1` 步驟 1～2）：guard → `load_config`（失敗的告警細節在 US4 補）→ 取鎖 → 開庫 → 寫 `run` → 依設定同步 `author`（首次看到啟用者寫 `activated_at`／`window_from`／`last_seen_enabled=1`；window_from＝`activated_at` 台北日期往前 14 天 00:00）；尚無抓取。驗收：T019 的 (10) 案例（首次看到啟用作者的 `activated_at`／`window_from`／`last_seen_enabled`）轉綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T023 [US1] 在 `poc/kb-mcp/substack_import.py` 實作主流程後半「抓取、判斷與寫入」（`contracts/cli.md §1` 步驟 4、7）：（步驟 3 補發通知，T024）→ 逐位啟用作者：robots → 條件請求 → `parse_feed` → 去重（`duplicate`／`dedupe_conflict`）→ 14 天窗 → `classify` 與 `html_to_text` → 每篇 `insert_article_with_images`（圖片列 `pending`；**N 類 `body_text` 傳 NULL、仍寫入 `content_html` 與圖片列**，FR-011）→ `poll_log`；作者失敗時記代碼、不寫該作者、繼續下一位；stdout 依 cli.md 範例（只含代號、狀態、計數，含 `dedupe_conflict` 計數但不入庫）。驗收：T019 其餘案例全綠（含 (10) 不退化）（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T024 [US1] 在 `poc/kb-mcp/substack_import.py` 實作通知：`format_article_notice(name, title, completeness)`（`completeness='N'` 時加固定提醒句 `NON_TEXT_REMINDER`，逐字同 `contracts/notifications.md §1`；其他類不加；FR-035）、`format_summary(...)`（含 `format_space_line()`；摘要不附 N 類提醒句、仍列非文字篇數，Q15／FR-035）、`send_queue()`（先補發 `pending`／`failed`，再依發布時間發新文章，每則間隔 1.5 秒，以注入的 `notifier` 呼叫 `notify.send_telegram`（`notify.py:61-95`），只看錯誤清單是否為空與數量、不記錯誤原文；失敗 attempts+1、達 3 → `abandoned`）；摘要觸發條件＝有新文章／告警／漏文提示。驗收：T020 全綠（含 N 類提醒 FR-035／SC-015）（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T025 [US1] 在 `poc/kb-mcp/substack_import.py` 實作排程日判斷與牆鐘預算：`schedule_day(now)`、`--scheduled` 啟動於 23:00～00:59 → `deferred`；本排程日已有實際執行 → `already_done`；22:00～22:59 啟動為 `schedule`、其他為 `catchup`；`RUN_BUDGET_SEC=1200`（`time.monotonic` 經注入 clock）、`remaining()` 傳給每次網路操作、期限檢查只在交易之間、到期寫完 `run`（`aborted_budget`）並釋放鎖、exit 1；不寫任何 05:00～18:00 時窗程式碼（FR-018；research R2）。驗收：T021 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T026 [P] [US1] 在 `poc/kb-mcp/tests/test_substack_isolation.py` 新增 **T-B 流水線不選取 011**（FR-021、SC-003；research R1）：暫存資料目錄同時放 010 fixture `articles.db`（以 010 既有測試的建庫方式建立、含待轉寫圖）＋以 `SubstackStore` 建立含已下載圖片檔、含圖位標記的 `substack.db`；呼叫 `ArticleStore.images_to_transcribe()`、`images_to_backfill()`、`pipeline_images_to_verify()`、`images_for_manual_export()`、`pipeline_pending_counts()` 與 `transcription_pipeline.run(["--data-dir", d, "--dry-run"])`；斷言回傳只含 010 fixture 的 image_id、`substack.db` 位元組與 mtime 不變（**預期**：設計正確時即綠；若失敗代表 010 會選到 011，須停下回報，不得改 010）
- [x] T027 [P] [US1] 建立 `poc/kb-mcp/tests/test_substack_no_leak.py`（V7、SC-005、FR-026；比照 `tests/test_investanchors_no_leak.py:70-85` 的四個面）：以夾具 `TITLE_MARK`／`BODY_MARK`／`SLUG_MARK`／`IMG_URL_MARK` 跑完整成功路徑，用 `investanchors_redact.assert_clean` 斷言：(1) stdout／stderr 不含四種標記；(2) 通知可含 `TITLE_MARK` 但不得含 `BODY_MARK`、`SLUG_MARK`、`IMG_URL_MARK`；(3) 資料庫中非資料通道的 TEXT 欄位（資料通道＝`article.title`／`link`／`link_norm`／`content_html`／`body_text`／`description`、`article_image.src_url`／`alt`／`caption`、`image_transcription.text`、`robots_cache.body`，其餘全部）不含任何標記；(4) 資料目錄下所有檔名不含標記（**預期**：T022～T025 若遵守規則即綠；任何失敗即為外洩缺陷）
- [x] T028 [US1] 檢查點：跑 US1 Independent Test（`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_*.py'`）全綠，並跑全套 `python3 -m unittest discover -s poc/kb-mcp/tests` 與 T002 基線比對無新增失敗（FR-031）；於本任務行尾記錄兩者數字（2026-11-25 實跑：`-p 'test_substack_*.py'` → **Ran 188 OK**〔Phase 2／3 的 141 ＋ 本階段新增 47：test_substack_import.py 40、test_substack_isolation.py 2〔T-B〕、test_substack_no_leak.py 5〕；全套 → **Ran 2528, failures=9, errors=4, skipped=59**，與 T002 基線〔2481／failures=9／errors=4／skipped=59〕**同名同數、無新增失敗**：test_us_stock_price_client.GetQuoteFallbackTest ×4〔error〕、test_article_manual_transcribe.ExportTest.test_output_folder_location_and_name、test_flight_search.SampleDatesTest.test_covers_requested_number_of_months、test_investanchors_delay_floor.JsClampTest ×4、test_transcription_pipeline.GuardTest.test_argv_has_no_billing_flags_and_fixed_safe_shape、test_transcription_pipeline.HappyPathTest ×2）

**Checkpoint**（2026-11-25 實跑）: MVP（US2＋US1）可在測試資料目錄完整驗收——US1 Independent Test 通過（空庫＋2 位作者只存 14 天內文章、立即再跑一次篇數不變、新文章存入並逐篇通知、假時鐘六個邊界 21:59／22:00／23:00／23:59／00:59／01:00 逐一通過、20 分鐘牆鐘預算強制中止並釋放鎖）。**本階段刻意尚未實作**（留給後續任務，不是漏做）：圖片下載（US3／T029～T032——摘要與 stdout 的圖片計數固定 0）、告警文字（US4／T035～T036——摘要「有告警」的觸發條件已接好，但 `alerts` 恆為 0）、`--backfill`／`--retry-images`／`--dry-run`／`--status`（US5／T042～T045——一律 exit 2＋代碼 `not_implemented`）

---

## Phase 5: User Story 3 — 圖片下載與缺圖補齊（Priority: P2）

**Goal**: 圖片只從白名單主機下載到 `substack_images/`；失敗記缺圖、每次排程補下載、連續 3 次放棄；PO 可要求重試、可增修白名單。

**Independent Test**: 讓一張圖連續失敗：第 1、2 次 `missing`、第 3 次 `abandoned`、之後零請求；`--retry-images` 後再試成功轉 `downloaded`；非白名單主機零請求，`add-image-host` 後重試可下載。

- [x] T029 [P] [US3] 先寫 `poc/kb-mcp/tests/test_substack_images.py`（**預期先失敗**；V3、V13、SC-008、SC-013、FR-014～FR-016、FR-034）：(1) 只允許 https；主機須與 `image_hosts` 或作者 feed 主機完全相同或為其子網域；非白名單 → **FakeHttp 零請求**、`last_error_code='host_not_allowed'`、`fail_count+1`；(2) 轉址只允許落在白名單主機，否則 `redirect_refused`；(3) `Content-Type` 非 `image/*` → `not_image`；>20MB → `too_large` 且中止讀取、`.part` 刪除；逾時 30 秒且取 `min(30, 剩餘)`；圖與圖間隔 `sleep(1)`；(4) 寫入：先寫 `.part` → `os.replace` → 才 UPDATE 為 `downloaded`（含 `sha256`、`bytes`、`file_path`＝`substack_images/<article_id>/<seq>.<ext>`）；副檔名由 Content-Type 白名單決定、路徑不含任何網址片段；realpath 必須在資料目錄之下；(5) 狀態機：`pending`→失敗→`missing(1)`→`missing(2)`→`abandoned(3)`，之後排程不再請求；`downloaded` ⇔ `file_path` 非 NULL 且檔案存在；(6) 磁碟滿（`ENOSPC`／`database or disk is full`）→ 丟 `DiskFullError`、刪 `.part`、狀態與 `fail_count` 不變；期限到 → 中斷、刪 `.part`、狀態與 `fail_count` 不變；(7) `retry(ids)`：只接受 `abandoned`／`missing`，重設 `fail_count=0` 後立即試一次；其他狀態或不存在的 id 明列拒絕；(8) 封面：`enclosure` 為 `image/*` 且不在內文 → `seq=0` 下載；`audio/*`／`video/*` 只記型別不下載；(9) **FR-016**：靜態掃描 `substack_images.py` 不得有刪除正式圖檔的程式路徑（`os.remove`／`unlink` 只允許作用於 `.part`）；(10) 不送任何模型（模組不 import 模型相關模組，由 T013 守門）
- [x] T030 [US3] 實作 `poc/kb-mcp/substack_images.py`：`download_one(store, image_row, *, fetch, allowed_hosts, deadline, sleep)`、`download_batch(...)`、`retry(store, ids, ...)`、主機比對 `host_allowed(host, allowed)`；安全規則照抄 `article_images.py:26-31`（拒絕跨主機轉址）與 `:47-97`（副檔名白名單、20MB、`.part`＋`os.replace`、固定路徑），**不 import `article_images`**、不用 `investanchors_limits` 的 5～15 秒間隔（research R0）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_images.py'` 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T031 [US3] 先在 `poc/kb-mcp/tests/test_substack_import.py` 新增整合測試（**預期先失敗**；US3-AS1～AS3、FR-015、FR-016）：新文章含 3 張圖、其中 1 張失敗 → 文章與其他 2 張已存、失敗圖 `missing`，**執行不算失敗**（`run.result='ok'`、exit 0，依 spec US3-AS2；已決定事項 #1），stdout 顯示缺圖數（`images: ... missing=1`）；**FR-015 字面斷言**：(a) 下載失敗不影響文章存檔（文章與其他圖片仍在）；(b) 每次排程執行除抓新文章外補下載先前缺圖，成功後狀態轉 `downloaded`；(c) 同一張圖補下載**連續失敗 3 次**即標 `abandoned`、之後排程**零請求**（不再自動重試）；(d) 健檢／摘要回報放棄張數；(e) PO 可用 `--retry-images` 要求對指定圖片重新嘗試（成功轉 `downloaded`）；**FR-016 斷言**：掃描**處理圖片的模組**（`poc/kb-mcp/substack_images.py` 與 `substack_import.py` 中操作 `substack_images/` 的部分；**不含** `substack_config.py` 的設定檔備份保留最新 10 份清理，那是刪 `.bak` 設定備份，與圖片無關，須列入例外白名單並在測試註明），不得出現刪除或清理已下載圖檔／`substack_images/` 目錄的程式路徑（`os.remove`／`os.unlink`／`.unlink(`／`shutil.rmtree`／`os.rmdir`，唯一例外是作用於 `.part` 暫存檔），也不得有任何保留期限或占用上限處理（依年齡／大小刪檔、超過上限即停止下載）；多次執行後 `substack_images/` 檔案數與位元組數只增不減；占用現況只由摘要與 `format_space_line()` 回報；下一次執行除抓新文章外補下載 `missing`／`pending`，成功轉 `downloaded`；圖片階段期限＝預算減 120 秒（18 分鐘）到即中止、仍發通知與摘要；`run.images_downloaded`／`images_missing`／`images_abandoned_now` 與摘要「圖片：本次下載 d 張、缺圖待補 m 張、放棄累計 a 張」一致（**此時才驗圖片行的實際數值**，T020 只驗格式；）；`--retry-images 3,5` 取鎖、只打圖片主機（FakeHttp 不出現 feed URL）、不接受 `downloaded` 狀態
- [x] T032 [US3] 在 `poc/kb-mcp/substack_import.py` 接上步驟 5（先下載本次新文章的圖片，再補下載 `pending`／`missing`；`allowed_hosts` 取自 `substack_config.allowed_image_hosts(cfg)`；期限 `RUN_BUDGET_SEC-120`）與 `--retry-images IMAGE_IDS` 動作（寫 `run`，`trigger='retry_images'`）；計數寫入 `run` 與摘要（圖片失敗不改變 `run.result`／退出碼，仍 `ok`／exit 0；T020 的圖片行改驗實值）。驗收：T031 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T033 [US3] 先在 `poc/kb-mcp/tests/test_substack_config.py` 新增 `add-image-host`／`remove-image-host` 測試（**預期先失敗**；FR-034）：小寫網域才接受；含路徑／埠／IP／大寫 → exit 2 不寫檔；已存在者重複新增拒絕；移除不存在者拒絕；作者 feed 主機不在 `image_hosts`、不能被移除；超過 20 個拒絕；每次寫入產生備份
- [x] T034 [US3] 在 `poc/kb-mcp/substack_config.py` 實作 `add-image-host HOST`、`remove-image-host HOST` 子命令（走 `write_config` 驗證＋備份＋原子寫入）（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_config.py'` 全綠，並在 `test_substack_images.py` 補一案例：`add-image-host` 後 `--retry-images` 可下載先前 `host_not_allowed` 的圖（SC-013）

**Checkpoint**（2026-11-26 實跑）: US3 Independent Test 通過（一張圖連續失敗 → `missing(1)`／`missing(2)`／`abandoned(3)`、放棄後排程零請求；`--retry-images` 後再試成功轉 `downloaded`；非白名單主機零請求、`add-image-host` 後重試可下載）。`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_*.py'` → **Ran 257 OK**（US1 後的 188 ＋ 本階段新增 69：test_substack_images.py 48、test_substack_import.py 13、test_substack_config.py 8）；全套 → **Ran 2597, failures=10, errors=4, skipped=59**：與 T002／T028 基線（2528／failures=9／errors=4／skipped=59）比對，總數 2528＋69＝2597 吻合、失敗項目**無新增**；唯一差異是既有的日期敏感測試 `test_flight_search.SampleDatesTest.test_excludes_requested_months` 在 2026-11-26 當天也開始失敗（同家族的 `test_covers_requested_number_of_months` 基線即已失敗），已用 `git archive HEAD` 乾淨副本（不含本階段任何改動）實跑確認該檔當天就是 2 個失敗，與 011 無關。

本階段的技術判斷（research／tasks 未明定，可逆、PO 可推翻）：
1. **圖片三個計數的語意**：`run.images_downloaded`＝本次成功下載張數；`run.images_missing`＝本次結束時仍待補張數（庫內 `pending`＋`missing`，對應摘要「缺圖待補 m 張」）；`run.images_abandoned_now`＝本次新標放棄張數；摘要「放棄累計 a 張」用庫內 `abandoned` 總數（欄名有 `_now`、摘要字樣是「累計」，兩者本來就不是同一個數）。
2. **副檔名只由 Content-Type 決定**（T029 字面要求）：與 010 圖片模組「先看網址副檔名」的做法不同，確保檔名完全不含網址片段；`image/*` 但不在白名單（例 `image/tiff`）記 `not_image`。
3. **新增兩個 `last_error_code`**：`write_failed`（非磁碟滿的寫檔 OSError，計一次失敗）；資料庫欄位是 TEXT、data-model 的代碼清單非窮舉。磁碟滿（ENOSPC／EDQUOT／`database or disk is full`）與期限到一律**不計** `fail_count`、狀態不變。
4. **圖片階段期限到不算執行失敗**：`run.result` 仍 `ok`、exit 0，但 `run.budget_exhausted=1`（data-model §1.5 明定該欄涵蓋「圖片階段到 18 分鐘強制中止」）；整體 20 分鐘中止才是 `aborted_budget`。
5. **`--retry-images` 有被拒絕的 id 時 exit 1、`run.result='partial'`**，比照既有 `--reclassify` 對不存在 id 的處置（`contracts/cli.md` 未明定 retry 的退出碼）。
6. **圖片用自己的 `default_fetch`**（`substack_images.fetcher_for(白名單)`）：feed 的 `default_fetch` 讀取上限是 5MB、轉址允許 `*.substack.com`，直接拿來抓圖會截斷大圖也會放寬主機，故另寫一份把白名單綁進轉址判斷。
7. **FR-016 靜態掃描只掃程式識別字**（`retention`／`max_total`／`older_than`／`disk_usage` 等）＋「刪除呼叫附近必須提到 `.part`」，不掃中文敘述——模組 docstring 本來就要寫「不設保留期限」，用中文詞掃會把「宣告沒有這件事」的句子當違規（第一版踩到）。掃描器附反向自我測試。

**本階段刻意尚未實作**（留給後續任務，不是漏做）：告警文字（US4／T035～T036）、`--backfill`／`--dry-run`／`--status`（US5／T042～T045）、健檢回報放棄張數（US7／T051～T054；本階段由摘要與 stdout 回報）。

---

## Phase 6: User Story 4 — 單一作者被擋或失敗不拖累其他人（Priority: P2）

**Goal**: 403／429／HTML 挑戰頁立即停手並告警；其他失敗依告警策略；不連續重試、不半寫入；磁碟滿中止；設定檔壞掉零請求。

**Independent Test**: 作者 A 回 403、B 正常 → A 只請求 1 次並立即告警、B 照常存入；兩種告警策略下逾時行為符合 FR-032。

- [x] T035 [US4] 先在 `poc/kb-mcp/tests/test_substack_import.py` 新增失敗隔離測試（**預期先失敗**；V4、SC-007、SC-011、FR-005、FR-009、FR-032）：(1) A 回 403／429／HTML 挑戰頁（各一案例）、B 正常 → A 本次只有 1 筆 feed 請求、無寫入、`blocked` 告警文字恰為 `contracts/notifications.md §3`（原因詞 `403`／`429`／`非 feed 回應`）且末尾有空間行；B 照常存入；(2) 上述在 `every_failure` 與 `consecutive_3` 下皆 100% 立即告警；(3) `timeout`／`network`／`parse_error`／`http_500`／`robots_disallow`／`robots_unavailable`／`too_large`／`redirect_refused`：該作者不寫入、既有資料與 `etag` 不被覆蓋、`consecutive_failures+1`；`every_failure` 每次發 `fetch_failed`（含連續次數 c）；`consecutive_3` 只在連續第 3 次發；中途一次 200／304 即歸零；(4) 告警策略切換後**下一次**失敗即依新策略；(5) 同次不重試（每作者 feed 請求數 ≤1）；(6) 有作者失敗、其餘完成 → exit 1、`run.result='partial'`；只有告警沒有新文章時仍發摘要（含空間行）；(7) 設定檔不存在／格式錯誤 → FakeHttp 零請求、`config_invalid` 告警、exit 2；(8) 文章交易中丟 `DiskFullError` → 立即中止、`run.result='aborted_disk'`、exit 4、`disk` 告警含剩餘 GB 與空間行、該篇無半寫入、先前已提交的文章保留（US4-AS4）；(9) 所有告警文字不含標題（`TITLE_MARK`）
- [x] T036 [US4] 在 `poc/kb-mcp/substack_import.py` 實作：`ALERT_TEXTS` 固定文字（比照 `investanchors_import.py:60-76` 慣例；四種代碼 `blocked`／`fetch_failed`／`disk`／`config_invalid`，每則末尾附 `format_space_line()`）、`should_alert(outcome, policy, consecutive)`（`blocked_403`／`rate_limited_429`／`challenge_html` 永遠 True）、作者級 `consecutive_failures` 更新（200／304 歸零、間隔跳過不變）、設定檔失敗路徑、磁碟滿中止路徑、`partial` 判定（只有作者失敗算 partial；圖片失敗不算）。驗收：T035 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T037 [US4] 先在 `poc/kb-mcp/tests/test_substack_config.py` 新增 `set-alert-policy` 測試（**預期先失敗**）：只接受 `every_failure`／`consecutive_3`，其他值 exit 2 不寫檔；寫入有備份
- [x] T038 [US4] 在 `poc/kb-mcp/substack_config.py` 實作 `set-alert-policy every_failure|consecutive_3`（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）。驗收：`test_substack_config.py` 全綠
- [x] T039 [P] [US4] 擴充 `poc/kb-mcp/tests/test_substack_no_leak.py`：對 403、挑戰頁、逾時、解析失敗、磁碟滿、設定檔錯誤、通知失敗各跑一次，例外訊息與回應內容故意含 `TITLE_MARK`、`SLUG_MARK`、假 Bot token，斷言四個面皆乾淨（只出現代碼）

**Checkpoint**（2026-11-26 實跑）：US4 Independent Test 通過；`test_substack_*.py` 286 項全綠（257→286，+29）；全套回歸 2626 項，failures=10／errors=4／skipped=59，與基線同名同數無新增（含當日 2 筆 `test_flight_search` 日期敏感失敗，與 011 無關）。獨立驗收對抗測試：403/429 不論策略立即告警、連續第 3 次才發且計數器正確歸零重置、策略切換下一次失敗即生效、預算中止零告警（連摘要都沒發）、外洩掃描對告警路徑有效（插入標題/token 會被抓到）。技術判斷：契約未列的失敗代碼歸類見程式 `FAILURE_REASON` 註解；20 分鐘預算用完不發告警（沿用既有規則）；`config_invalid` 只在完整排程/手動流程發，`--backfill`／`--retry-images` 不發；磁碟滿告警剩餘空間取不到時顯示「無法取得」。

**本階段刻意尚未實作**（留給後續任務）：`--backfill`／`--dry-run`／`--status`（US5／T042～T045）、健檢回報放棄張數（US7／T051～T054）、備份與健檢整合（US7）。

---

## Phase 7: User Story 5 — 用對話管理追蹤清單與輪詢頻率（Priority: P2）

**Goal**: 透過 CLI 新增／停用／重新啟用作者、調整最小間隔（下限 10 分鐘）；最小間隔守衛；重新啟用套 14 天窗；手動追補；唯讀狀態與 dry-run。

**Independent Test**: 新增一位、停用一位後下次執行只輪詢新增者與未停用者；連續輪詢同一作者兩次，第二次因間隔被跳過且記錄；`set-interval 9` 被拒。

- [x] T040 [US5] 先在 `poc/kb-mcp/tests/test_substack_config.py` 新增管理子命令測試（**預期先失敗**；FR-002、FR-004）：`add --key --name --feed-url`（驗證規則同 T007、key／feed_url 重複拒絕）、`enable KEY`／`disable KEY`（不存在的 key 拒絕）、`set-interval 30` 成功、`set-interval 9` → exit 2 且輸出含「下限為 10 分鐘」且檔案位元組不變、`set-interval 1441` 拒絕；不提供刪除作者子命令；每次寫入有備份、只保留 10 份
- [x] T041 [US5] 在 `poc/kb-mcp/substack_config.py` 實作 `add`、`enable`、`disable`、`set-interval` 子命令（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）。驗收：`test_substack_config.py` 全綠
- [x] T042 [US5] 先在 `poc/kb-mcp/tests/test_substack_import.py` 新增測試（**預期先失敗**；US5-AS1～AS5、FR-002、FR-004、FR-008）：(1) 停用作者不被請求、其已存文章仍在且 `--status` 可見；(2) 新增作者下次執行被納入，以其 `activated_at` 套 14 天窗；(3) `last_seen_enabled` 0→1（重新啟用）→ `activated_at` 重寫、窗口重算；首次啟用即使抓取失敗也寫 `activated_at`、重跑沿用；`--dry-run` 不寫 `last_seen_enabled`；(4) **最小間隔**：排程執行時 `now - last_request_at < min_poll_interval` → `skipped_interval`、`poll_log.requested=0`、零請求、不告警、`consecutive_failures` 不變；手動執行同情況印出「還需等待 N 分鐘」；改間隔後下一次以新值判斷；(5) **追補** `--backfill KEY`：取鎖、間隔內拒絕並回報剩餘分鐘、請求**不帶** `If-None-Match`、忽略 14 天窗、去重後存入 `source='backfill'`、**逐篇通知**（B3）＋摘要標「追補」；stdout 依 cli.md 範例含 `feed_items`／`already`／`stored`／`oldest_in_feed` 與固定提示「早於 … 的文章 feed 已不提供，無法取得（不會改抓其他來源）」；FakeHttp 只出現該作者的 robots 與 feed URL（不抓單篇網頁）；不存在或已停用的 key → 拒絕並 **exit 2**、零網路、不寫庫、不寫通知（已決定事項 #5）
- [x] T043 [US5] 在 `poc/kb-mcp/substack_import.py` 實作最小間隔守衛、重新啟用偵測（`last_seen_enabled`）、`--backfill AUTHOR_KEY` 動作（`run.trigger='backfill'`；不存在或已停用的作者 → 拒絕並 exit 2）。驗收：T042 全綠（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）
- [x] T044 [US5] 先在 `poc/kb-mcp/tests/test_substack_import.py` 新增 `--dry-run` 與 `--status` 測試（**預期先失敗**；cli.md §1）：兩者零網路（FakeHttp 0 請求）、`substack.db` 不存在時不建立、存在時位元組不變；`--dry-run` 驗證設定檔並列出每位作者「會請求／會因間隔跳過（剩餘分鐘）／停用」與缺圖待補張數；`--status` 列作者狀態、P/F/N（**有效完整度**，註明被重判過的篇數）、圖片四種狀態張數、未通知篇數、最近 5 次執行；輸出不含標題
- [x] T045 [US5] 在 `poc/kb-mcp/substack_import.py` 實作 `--dry-run`（僅限無動作或 `--scheduled` 組合；`--reclassify --dry-run` 已於 T018）與 `--status`，皆以 `SubstackStore.open_readonly` 唯讀開庫。驗收：T044 全綠；手動 `python3 poc/kb-mcp/substack_config.py --data-dir poc/data-test-substack init && python3 poc/kb-mcp/substack_import.py --data-dir poc/data-test-substack --dry-run`（quickstart §2）成功且未發出網路請求（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）

**Checkpoint**（2026-11-26 實跑）：US5 Independent Test 通過；`test_substack_*.py` 325 項全綠（286→325，+39）；全套回歸 2665 項，failures=10／errors=4／skipped=59，用 `git stash` 建當下基線比對完全同名同數無新增。獨立驗收對抗測試：追補受 feed 20 篇上限限制且明確回報取不到（不改抓其他來源）、追補不下載圖片（圖片列留 pending）、追補在最小間隔內被拒絕（exit 2、零請求）、缺漏/停用作者檢查在取鎖與開庫之前（空目錄驗證無殘留檔案）、`--dry-run`／`--status` 零網路（monkeypatch socket 丟例外仍 exit 0）、不取鎖、不需資料庫存在。技術判斷：追補仍計入最小間隔並保留新 ETag；追補通知與先前未發出的一起發，逐篇、按發布時間舊到新，摘要標「追補」；`--status` 對「設定檔存在但庫不存在」與「庫存在但設定檔不存在」兩種情境行為不對稱（分別 exit 2／exit 0），cli.md 未明文覆蓋此邊界組合但行為自洽，經讀碼與實跑雙重確認。

**本階段刻意尚未實作**（留給後續任務）：健檢回報放棄張數與 token 排程間隔提醒（US7／T051～T058）、備份整合（US7）。

---

## Phase 8: User Story 6 — 手動少量轉寫試跑（Priority: P3）

**Goal**: 只能手動、兩段式確認碼、只轉表格圖、每作者 1～3 篇 F 類近期文章；結果只寫 `substack.db`；010 零差異。

**Independent Test**: 以假 claude runner 跑 `--plan` → `--run --confirm` → `--report`；轉寫結果可直接讀庫查到；`articles.db` 位元組前後相同、全程未被開啟；無確認碼或由 `com.alphavibe.*` 排程啟動時拒絕。

- [x] T046 [P] [US6] 先寫 `poc/kb-mcp/tests/test_substack_transcribe.py`（**預期先失敗**；FR-020、FR-022～FR-024、SC-009）：(1) `--plan` 零網路、FakeClaudeRunner 0 次、唯讀（庫不存在不建、存在位元組不變）；輸出內部 id、作者代號、發布日、已下載圖數、總圖數、預估呼叫次數＝圖數×2、6 碼確認碼；不含標題；(2) **選取規則（FR-023）**：每位啟用作者取有效完整度（`article_effective`，含重判）為 F 且至少 1 張 `downloaded` 圖的最新 N 篇；`--per-author` 只收 1～3（0、4 拒絕）；`--article-ids` 每篇須通過同規則且每作者 1～3 篇；無符合文章的作者明列「無符合條件文章」、不自動放寬；重判把某篇 P→F 後可被選中；(3) 確認碼＝排序後 image_id 清單＋台北日期的雜湊前 6 碼；(4) `--run` 拒絕（exit 2、0 次呼叫）：確認碼不符、跨日（FakeClock）、選取結果變了；**被拒絕的執行不寫 `transcription_trial` 紀錄**（拒絕前後該表列數不變，只回退出碼與訊息；已決定事項 #3）；(5) **T-D `XPC_SERVICE_NAME`**：未設、`0`、`application.com.microsoft.VSCode.1234.5678` → 不因此拒絕；`com.alphavibe.substackimport`、`com.alphavibe.transcriptionpipeline` → 拒絕；(6) 鎖被占用 → exit 3；(7) `check_flags`／`check_auth` 判定非 claude.ai 訂閱 → exit 5、`result='aborted_auth_mode'`、0 次轉寫呼叫；登入失效 → `aborted_login`；中途撞使用量上限 → 立即停止、exit 5、`aborted_usage_limit`、記 `reset_hint`；(8) 每張圖先 reader-1（預設 `sonnet`）再驗證者（預設 `opus`、不同別名、`verify_text=` 帶 reader 結果）；非表格 → `is_table=0`、無 text；(9) `transcription_trial` 欄位（`articles`、`images_attempted`／`ok`／`not_table`／`failed`、`claude_calls`＝實際呼叫次數、`models`、`result`、`confirm_code`）與 `image_transcription` 列正確，且可用 `sqlite3.connect("file:...substack.db?mode=ro", uri=True)` 直接查到 text（FR-024）；(10) `--report`（含 `--trial-id ID`）唯讀；(11) 不提供 `--enable`；`ClaudeCli` 以 `token_getter=None` 建立、`keychain_secrets` 不在 `sys.modules`、未呼叫 `security`；(12) 傳給子行程的環境（`ClaudeCli.build_env` 結果）含 `USER` 與 `LOGNAME`、不含 `CLAUDE_CODE_*`；(13) `--reader1-model`、`--verifier-model`、`--claude-bin`、`--timeout-sec` 參數會傳到 `ClaudeCli`
- [x] T047 [US6] 實作 `poc/kb-mcp/substack_transcribe.py`：只 import `claude_cli_runner.ClaudeCli`（`claude_cli_runner.py:412-428` 建構、`:453-490` `check_flags`／`check_auth`、`:492-535` `call(..., verify_text=...)`）與 `transcription_pipeline.prepare_workdir`（`:99-127`）；`--plan`／`--run --confirm CODE`／`--report`、`--per-author N`／`--article-ids IDS`、`--reader1-model`／`--verifier-model`／`--claude-bin`／`--timeout-sec`；第一步 guard、`--run` 取同一把 `.substack_import.lock`；讀寫只限 `substack.db`；不跑 PaddleOCR；不自造子行程環境；stdout 只印數字與代碼；退出碼依 cli.md（5＝使用量上限／登入失效／登入方式不符）；被拒絕的執行不寫試跑紀錄（註解與字串也不得出現 `articles.db`／`article_store`／`ArticleStore` 字樣，T-A 掃全文）。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_transcribe.py'` 全綠
- [x] T048 [US6] **T-C 攔截法可行性驗證（先於 T049；T-C 是全案最脆弱的測試，攔截法本身須先被證明可行）**：在 `poc/kb-mcp/tests/test_substack_isolation.py` 新增小型 `InterceptFeasibilityTest`（與 T047 無相依，用最小假腳本即可）：以 `/usr/bin/python3`（3.9.6）起**全新子行程**，包裝腳本先 monkeypatch `sqlite3.connect`、`builtins.open`、`os.open` 並把每次被開啟的路徑（`file:` URI 先還原成檔案路徑、再 `os.path.realpath`）寫入記錄檔，再 `runpy` 一支最小腳本，該腳本分別以 `sqlite3.connect(路徑)`、`sqlite3.connect('file:…?mode=ro', uri=True)`、`open(路徑)`、`os.open(路徑, os.O_RDONLY)` 各開一個暫存檔。斷言：四種開啟方式的路徑都出現在記錄中；`import sqlite3`／`import runpy` 之後再 patch 仍能攔到；patch 後再 import 一個會在模組頂層 `import sqlite3` 的標準庫模組仍被攔到；子行程退出碼 0、不污染父行程。**若任一種攔不到**：停下回報主對話（說明哪種開啟法漏網），不得自行降低 T049 的斷言標準或改成只做靜態檢查。驗收：此測試在 3.9.6 子行程全綠後才可開始 T049
- [x] T049 [US6] （**全案最脆弱的測試**：依賴 T048 已證明可行的攔截法；子行程環境、假 claude 協定、路徑正規化任一環出錯都會變成偽陰性或偽陽性，失敗時先查攔截記錄再懷疑 011 程式）在 `poc/kb-mcp/tests/test_substack_isolation.py` 新增 **T-C 手動轉寫不動 010（含執行期證明）** 與 **T-D 排程掃描**（V16、FR-024、FR-031、SC-004）：(1) 暫存資料目錄放 010 fixture `articles.db` 與含已下載圖的 `substack.db`；於**全新子行程**執行一支包裝腳本：先 monkeypatch `sqlite3.connect`、`builtins.open`、`os.open` 記錄所有路徑，並讓 `article_store.ArticleStore.__init__` 拋例外，再以 `runpy` 執行 `substack_transcribe.py --plan` 與 `--run --confirm <碼>`（`--claude-bin` 指向測試建立的假 claude 腳本，依 `claude_cli_runner.py:453-535` 的協定回應 flags／auth／轉寫輸出）；子行程環境明確包含 `USER`、`LOGNAME`；(2) 斷言：沒有任何被開啟路徑的 realpath 以 `articles.db`、`articles.db-journal`、`articles.db-wal` 結尾；流程照常完成；`articles.db` 前後位元組相同（比照 `tests/test_article_verification.py:868-875` 的 `db_bytes()`）；資料目錄未新建 `articles.db`；注入的 LaunchAgents 目錄無新檔；(3) **T-D**：`ops/launchd/*.plist` 皆不含 `substack_transcribe`
- [x] T050 [US6] 檢查點：`python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack_*.py'` 全綠；全套與 T002 基線比對無新增失敗

**Checkpoint**（2026-11-26 實跑）：US6 自動化部分完成；`test_substack_*.py` 376 項全綠（325→376，+51）；全套回歸 2716 項，failures=10／errors=4／skipped=59，用 `git stash -u` 建當下基線比對完全同名同數無新增；010 相關既有失敗集合逐一核對不變。010 既有三檔（claude_cli_runner.py／transcription_pipeline.py／article_store.py）`git hash-object` 比對位元組完全不變。獨立驗收對抗測試：故意讓函式開啟 010 庫，T-C 守門立即 FAIL（證明非裝飾性斷言）；兩段式確認碼對選取集合雜湊，換文章或跨日即失效；XPC_SERVICE_NAME 只擋 `com.alphavibe.*`，手動終端機環境放行；選取規則只收有效完整度 F 類、每作者 1～3 篇。
**T046(11)「`keychain_secrets` 不在 `sys.modules`」照字面無法達成**（重用 010 的 `ClaudeCli` 必然連帶載入，因果鏈已查證：`claude_cli_runner.py` 頂層 import `article_transcribe`，其頂層 import `keychain_secrets`）：改用等效執行期證明（`get_secret` 從未被呼叫、`token_getter=None` 寫死不可覆寫、子行程只執行 `claude` 無 `security`、子行程環境不含 `CLAUDE_CODE_*`）。獨立驗收判定：此為設計層級保證而非僥倖未觸發，接受此偏離，不要求再處理。

真實試跑見 T074【須 PO 當下確認】。

---

## Phase 9: User Story 7 — 維運：空間、備份、健檢與提醒（Priority: P3）

**Goal**: 新庫與圖片納入每日備份（資料庫壓縮＋圖片增量鏡像）；健檢每日報空間現況、放棄張數、上次成功與失敗統計、全文占比提醒、token 排程間隔提醒；對 010 既有測試零影響。

**Independent Test**: 跑健檢確認三個新項目輸出符合 `contracts/health-output.md`、空間項無判定字眼；跑備份確認產生 `substack-*.db.gz` 與鏡像；token 排程設得過近出現提醒且 plist 未被修改。

- [ ] T051 [US7] 修改前再跑一次 `python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_backup_databases.py'` 與 `-p 'test_check_scheduled_jobs.py'`，與 T002 記錄比對一致後才動 `poc/kb-mcp/backup_databases.py`、`poc/kb-mcp/check_scheduled_jobs.py`（research R7「對既有測試的影響」逐項確認：`test_backup_databases.py:90-97` 前綴不撞、`:112-124` 不受影響；`test_check_scheduled_jobs.py:166-175` 只依 critical、`:568-570` 只 `assertIn` 名稱）
- [ ] T052 [P] [US7] 先在 `poc/kb-mcp/tests/test_backup_databases.py` **只新增**案例（**預期先失敗**；US7-AS3、V9）：`substack.db` 不存在 → 略過不報錯；存在 → 產生 `substack-*.db.gz` 且完整性檢查 ok；`mirror_dir(src, dest)` 只複製目的端不存在或大小不同的檔案、**不刪除**目的端多出的檔案、完成後寫 `.last_sync`、來源目錄不存在 → 印一行略過且不建目錄；第二次執行複製 0 個；`main()` 在資料庫迴圈後呼叫鏡像；既有案例一行都不改
- [ ] T053 [US7] 修改 `poc/kb-mcp/backup_databases.py`：`OPTIONAL_DATABASES = ("articles.db", "substack.db")`（`:45`）、新增 `OPTIONAL_DIR_MIRRORS = (("substack_images", "substack_images"),)` 與 `mirror_dir()`（目的地 `~/AlphaVibe-backups/mirror/substack_images/`）、`main()`（`:136-161` 資料庫迴圈之後）呼叫；不改其他行為。驗收：`test_backup_databases.py` 全部（含既有）綠，既有案例結果與 T051 一致
- [ ] T054 [P] [US7] 先在 `poc/kb-mcp/tests/test_check_scheduled_jobs.py` **只新增**案例（**預期先失敗**；SC-006 後半、SC-010、**FR-013 全文占比異常檢查**、FR-028、FR-029）：**`check_substack_import`**：庫不存在 → ok「尚未建立」且不建檔；無執行紀錄 → ok；最後一次實際排程執行（排除 `deferred`／`already_done`）超過 3 天 → warning；作者連續失敗 ≥3 → warning；`aborted_budget` → warning；通知已放棄 → warning；**FR-013**：比較日 <7 → 只報「可比較天數 N，未滿 7 天，不判斷」；最近抓取日 F 占比與前 7 個日曆日中有文章日子的平均相差 >30 個百分點 → warning 且以「提醒：」開頭、只報現況；只計 `source` 為 `schedule`／`manual`（追補不計）；**用原判斷**（插入重判紀錄不改變結果）；**確認不新增 N 類異常提醒**（PO 未要求；N 類文章數不觸發 warning，只在 P/F/N 計數中顯示，與 FR-013 只看 F 占比一致）；每日必有一筆 ok 摘要含上次成功與耗時、近 7 天請求統計（200／304／失敗／被擋／間隔跳過）、P/F/N（有效完整度＋被重判篇數）、圖片已下載／缺圖／放棄、未通知數、全文占比、空間行；**禁字掃描**：本函式所有 detail 不得含「異常」「不足」「危險」「超標」「閾值」（「提醒：」開頭的現況句允許）；唯讀開庫前後位元組不變
- [ ] T055 [US7] 先在 `poc/kb-mcp/tests/test_check_scheduled_jobs.py` **只新增**案例（**預期先失敗**；FR-029、US7-AS3）：**`check_substack_backup`** 依 `contracts/health-output.md §2` 四種情況（`substack.db` 不存在 → ok 略過；找不到 `substack-*.db.gz` 或最新一份 >30 小時 → warning；`.last_sync` 不存在或 >30 小時 → warning；正常 → ok）；唯讀、不建檔；**禁字掃描**：所有 detail 不得含「異常」「不足」「危險」「超標」「閾值」
- [ ] T056 [US7] 先在 `poc/kb-mcp/tests/test_check_scheduled_jobs.py` **只新增**案例（**預期先失敗**；FR-030、SC-010）：**`check_token_schedule_gaps`**（注入 `agents_dir` 與假 plist、010 fixture `articles.db` 的 `pipeline_run`）：皆未安裝 → ok；無耗時紀錄 → ok「無耗時紀錄、無法判斷」；相鄰觸發間隔 < 前者最近 10 筆最大耗時＋30 分 → warning（以「提醒：」開頭、含「系統不會自動修改」）；單一時段間隔 1440；**從不回 critical**；執行前後假 plist 位元組與 mtime 不變（FR-030 不自動改）；三個名稱（`substack_import`／`substack_backup`／`token_schedule_gaps`）皆在 `CHECKS`（`assertIn`）；**禁字掃描**：所有 detail 不得含「異常」「不足」「危險」「超標」「閾值」
- [ ] T057 [US7] 修改 `poc/kb-mcp/check_scheduled_jobs.py`（一個實作任務同時滿足 T054／T055／T056 三組測試）：新增 `check_substack_import(data_dir)`、`check_substack_backup(data_dir, backup_dir=DEFAULT_BACKUP_DIR)`（比照 `check_articles_backup` `:161-178`，另檢查鏡像 `.last_sync`）、`check_token_schedule_gaps(data_dir, agents_dir=~/Library/LaunchAgents)` 與常數 `TOKEN_JOBS`（目前只有 `com.alphavibe.transcriptionpipeline`，耗時來源以 `ArticleStore.open_readonly`（`article_store.py:473-485`）唯讀讀 `pipeline_run`（`:148-151`）；以 `plistlib` 讀 `StartCalendarInterval`）；登記進 `CHECKS`（`:450-458`）；`substack.db` 以 `mode=ro` 唯讀開啟；**不改** `should_notify`（`:489`）與 `notify.format_health_message`（`notify.py:98`）。驗收：T054／T055／T056 全綠、`test_check_scheduled_jobs.py` 全部（含既有）綠，既有案例結果與 T051 一致；手動 `python3 poc/kb-mcp/check_scheduled_jobs.py --data-dir poc/data-test-substack --state-file "" --json`（V8）輸出含三個新項目
- [ ] T058 [US7] 檢查點：`python3 -m unittest discover -s poc/kb-mcp/tests` 全套與 T002 基線比對，差異只能是新增的通過案例（FR-031）；並手動跑 `python3 poc/kb-mcp/backup_databases.py --data-dir poc/data-test-substack --dest "$(mktemp -d)"`（V9）確認有 `substack-*.db.gz` 與 `mirror/substack_images/`

**Checkpoint**: US7 Independent Test 通過

---

## Phase 10: Polish & Cross-Cutting（排程檔、文件、回歸、獨立驗收、部署、首跑）

- [ ] T059 [P] 先在 `poc/kb-mcp/tests/test_substack_isolation.py` 新增 plist 結構測試（**預期先失敗**：plist 尚不存在；FR-017、FR-029、research R9）：以 `plistlib` 讀 `ops/launchd/com.alphavibe.substackimport.plist`：`Label`＝`com.alphavibe.substackimport`；`ProgramArguments`＝`/usr/bin/python3`、`/Users/stander/My_project/AlphaVibe-prod/poc/kb-mcp/substack_import.py`、`--data-dir`、`/Users/stander/My_project/AlphaVibe-prod/poc/data`、`--scheduled`；`StartCalendarInterval` 恰為兩筆 `{Hour:22,Minute:0}` 與 `{Hour:1,Minute:0}`；無 `RunAtLoad`、無 `KeepAlive`；`EnvironmentVariables` 只有 `PATH`（`/usr/bin:/bin:/usr/sbin:/sbin`）與 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`；`StandardOutPath`／`StandardErrorPath` 為 `~/Library/Logs/alphavibe-substack.log`／`alphavibe-substack.err.log` 的展開路徑，且符合 `rotate_logs.py:30` 的 `DEFAULT_LOG_GLOB`（`fnmatch`）；`WorkingDirectory` 為 AlphaVibe-prod
- [ ] T060 建立 `ops/launchd/com.alphavibe.substackimport.plist`（照 T059 規格；格式比照 `ops/launchd/com.alphavibe.transcriptionpipeline.plist`，附註解說明：22:00 主排程、01:00 補跑、安裝須 PO 當下確認、改 plist 時先 bootout 並確認舊行程結束再 bootstrap）。驗收：T059 全綠；`plutil -lint ops/launchd/com.alphavibe.substackimport.plist` OK
- [ ] T061 [P] 更新 `specs/011-substack-fetch-store/quickstart.md`（含確認「工作位置」一節與 §2／§3 的 worktree 路徑與實作一致）：若實作中有與文件不同的實際指令或輸出（例如退出碼、`--dry-run` 輸出欄位），以實測為準更新 §2～§9；確認 §8 回滾三層（停排程 `launchctl bootout gui/$(id -u)/com.alphavibe.substackimport`／程式回到舊 commit 的 `ops/deploy.sh`／資料以 `~/AlphaVibe-backups/daily/substack-*.db.gz` 與 `mirror/substack_images/` 還原，不動 `articles.db`）的指令與檔名和實作一致；確認 §9 記載新增 token 排程須加進 `TOKEN_JOBS`。不改 spec.md／plan.md／research.md／contracts（有差異列入 PR 說明請主對話處理）
- [ ] T062 [P] 更新 `CLAUDE.md` 的 011 段落：把「plan 完成、尚未產生 tasks、沒有程式碼」改為實際現況（程式完成與否、測試數、是否部署、是否安裝排程），並在「常用查證點」加一條：011 程式位置（`poc/kb-mcp/substack_*.py`）、測試指令（`-p 'test_substack*.py'`）、手動測試資料目錄 `poc/data-test-substack/`、接手先讀 `specs/011-substack-fetch-store/quickstart.md`；改前依 CLAUDE.md 規則（git 追蹤檔靠 git 保護）
- [ ] T063 全套回歸（FR-031、SC-003、SC-004、SC-005）：在開發用獨立 worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`；主資料夾可能被其他 session 切到別的分支，不要假設其分支）跑 `python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack*.py'` 與 `python3 -m unittest discover -s poc/kb-mcp/tests`，與 T002 基線逐項比對（失敗清單必須相同、總數只增加 011 新測試）；結果附記在本任務行尾
- [ ] T064 bytecode 快取排除（CLAUDE.md 2026-09-03）：對每個 `poc/kb-mcp/substack_*.py` 跑 `python3 -c "import sys; sys.path.insert(0,'poc/kb-mcp'); import <模組> as m; print(m.__cached__)"`，確認快取路徑與來源檔一致；再以乾淨副本 `D=$(mktemp -d) && git archive HEAD | tar -x -C "$D" && cd "$D" && python3 -m unittest discover -s poc/kb-mcp/tests -p 'test_substack*.py'`（須先 commit 本功能異動，或用 `git stash create` 的 ref）重跑一次，結果須與 T063 相同
- [ ] T065 【須 PO 當下確認】提交與推送：在開發用獨立 worktree `/Users/stander/My_project/AlphaVibe-011`（分支 `011-substack-fetch-store`；主資料夾可能被其他 session 切到別的分支，不要假設其分支）提交本功能全部異動（`poc/kb-mcp/substack_*.py`、`poc/kb-mcp/tests/`、`ops/launchd/com.alphavibe.substackimport.plist`、`.gitignore`、`CLAUDE.md`、`specs/011-substack-fetch-store/`）（commit message 依 repo 慣例、結尾附 attribution），推送並開 PR 到 `function/alphavibe`（PR 描述附 T063／T064 結果、本檔「已決定事項」與未處理清單、哪些任務是【須 PO 當下確認】尚未執行）；不切換分支、不 force push；**push 與開 PR 都須 PO 當下確認**，未確認前只做本地提交
- [ ] T066 【GATE】fresh agent 獨立驗收（全域規則「驗證不自驗」；不得由實作者自己做）：主對話依 `~/.claude/rules/30-delegation-templates.md` 第 6 型派 agent，輸入＝spec.md 原文、quickstart.md §4 V1～V16、PR diff；agent 在 `git archive` 乾淨副本實際跑測試並逐條給 PASS/FAIL＋證據；**否決條件**至少含：任一 V 項無證據、`substack_*.py` 出現 `articles.db`、排程路徑有模型呼叫、通知含網址、010 全套結果與基線不同、任何測試被跳過或改寬來過關；FAIL 項修正後重驗
- [ ] T067 【須 PO 當下確認】FR-013 暫解讀確認（plan.md「仍待 PO 確認 #2」、spec Q11）：向 PO 說明現行算法（最近抓取日 F 占比 vs 近 7 天有文章日子的平均，差 >30 個百分點提醒）與在每天 0～3 篇時常誤提醒的風險，請 PO 選「維持」或「改為 7 天對 7 天且至少 5 篇才判斷」；若改，只修改 `poc/kb-mcp/check_scheduled_jobs.py` 的 `check_substack_import` 占比函式與 `poc/kb-mcp/tests/test_check_scheduled_jobs.py` 對應案例（research R7）。**部署（T068）前須有答案**
- [ ] T068 【須 PO 當下確認】正式環境部署：PR 合併進 `function/alphavibe` 後，PO 確認才執行 `cd /Users/stander/My_project/AlphaVibe-prod && git fetch origin function/alphavibe && bash <(git show origin/function/alphavibe:ops/deploy.sh)`（`ops/deploy.sh` 不需修改；011 無前端、無常駐服務變更），確認輸出的健康檢查通過並記下回滾指令
- [ ] T069 【須 PO 當下確認】正式設定檔與 dry-run：PO 確認後執行 `cd /Users/stander/My_project/AlphaVibe-prod && ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_config.py --data-dir poc/data init`、`... validate`、`ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_import.py --data-dir poc/data --dry-run`（零網路），把 `show` 與 dry-run 結果回報 PO
- [ ] T070 【須 PO 當下確認】首次真實抓取（對 Substack 的真實請求；PO 在場；quickstart §5.3 首跑檢核）：(1) **先確認資料磁碟實際剩餘空間**：`df -h /System/Volumes/Data`、`df -h /Users/stander/My_project/AlphaVibe-prod/poc/data` 與 `/usr/bin/python3 -c "import shutil; print(shutil.disk_usage('/Users/stander/My_project/AlphaVibe-prod/poc/data'))"`（`AlphaVibe-prod/poc/data` 是指向資料夾 `AlphaVibe/poc/data` 的 symlink）（`df -h /` 是系統卷，不代表資料磁碟；2026-11-20 實測資料卷 91% 已用、約 20Gi 可用），回報 PO 由其判斷是否繼續；(2) `cd /Users/stander/My_project/AlphaVibe-prod && ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_import.py --data-dir poc/data`；(3) 確認：兩個 feed 皆 200（FOMO 失敗時依 `contracts/config-format.md` 以 `substack_config.py` 改為 `https://fomosoc.substack.com/feed` 後，經 PO 同意再跑一次）、新增約 25 篇、P/F/N 分布與 2026-11-19 實測相近（約 35／40 為 P）、Telegram 收到逐篇通知＋1 則摘要且無連結、`--status` 的缺圖張數、是否有 `host_not_allowed`（若有，評估後經 PO 同意以 `add-image-host` 補並 `--retry-images`）、`run` 表耗時；以 `du -sh poc/data/substack_images` 估算鏡像翻倍後的占用並告知 PO（research R7 鏡像三項限制）；只執行一次，失敗不自行重跑、不改參數再試
- [ ] T071 【須 PO 當下確認】`XPC_SERVICE_NAME` 假設實測（research R1 T-D 標為未實測）：PO 同意後，在 session scratchpad 或 `/tmp/`（不放 repo、不放 `ops/launchd/`）建立臨時 plist（`Label`＝`com.alphavibe.xpcprobe`、`ProgramArguments`＝`/usr/bin/python3 -c "import os;print(os.environ.get('XPC_SERVICE_NAME'))"`、`RunAtLoad`＝true、輸出到 scratchpad 檔），`launchctl bootstrap gui/$(id -u) <plist>` → 讀輸出 → `launchctl bootout gui/$(id -u)/com.alphavibe.xpcprobe` → 確認 `launchctl print` 查不到 → 刪除臨時 plist；預期輸出 `com.alphavibe.xpcprobe`。若不符，回報 PO 與主對話（主防線確認碼不受影響；次防線需另議），不自行改程式
- [ ] T072 【須 PO 當下確認】安裝排程（PO 說「安裝」後才執行；FR-020）：`cp /Users/stander/My_project/AlphaVibe-prod/ops/launchd/com.alphavibe.substackimport.plist ~/Library/LaunchAgents/` → `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alphavibe.substackimport.plist` → `launchctl print gui/$(id -u)/com.alphavibe.substackimport | grep -i state`；**不** kickstart（避免安裝即打站方）；回報安裝結果與回滾指令 `launchctl bootout gui/$(id -u)/com.alphavibe.substackimport`
- [ ] T073 【須 PO 當下確認】隔天上線驗證（SC-001、SC-014、Q-105）：`tail -n 40 ~/Library/Logs/alphavibe-substack.log` 確認 22:00 執行、01:00 為 `already_done`、耗時遠小於 20 分鐘且未跨入 23:00；`~/Library/Logs/alphavibe-substack.err.log` 無外洩內容（以 `grep -E 'https?://'` 抽查應為 0）；04:00 健檢狀態檔 `~/Library/Logs/alphavibe-health.json` 含 `substack_import`／`substack_backup`／`token_schedule_gaps` 三項；`ls ~/AlphaVibe-backups/daily/substack-*.db.gz` 與 `~/AlphaVibe-backups/mirror/substack_images/.last_sync` 存在；結果回報 PO
- [ ] T074 【須 PO 當下確認】手動轉寫試跑（會消耗 claude.ai 訂閱用量；US6、SC-009、SC-004；quickstart §7）：(1) 試跑前 `shasum -a 256 /Users/stander/My_project/AlphaVibe-prod/poc/data/articles.db`（symlink，等同正式庫） 並跑 010 全套；(2) `cd /Users/stander/My_project/AlphaVibe-prod && ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1 /usr/bin/python3 poc/kb-mcp/substack_transcribe.py --data-dir poc/data --plan --per-author 1`，把篇數、圖數、預估呼叫次數、確認碼貼給 PO；**等 PO 在當下對話說確認**（別的對話的同意不算）；(3) `... --run --confirm <確認碼> --per-author 1`；(4) `--report` 與 `sqlite3 "file:poc/data/substack.db?mode=ro" "SELECT image_id, is_table, length(text) FROM image_transcription ORDER BY image_id DESC LIMIT 10;"` 確認可查找；(5) 再次 `shasum -a 256` 比對 `articles.db` 相同、010 全套結果與試跑前相同、`launchctl list | grep -i substack` 只有 `substackimport`；試跑必須在 23:40 流水線以外的時段執行，且同一時間不得有 010 轉寫在跑；結果回報 PO

---

## Dependencies & Execution Order

### Phase 依賴

- **Setup（T001～T004）**：無依賴；T003、T004 可平行。
- **Foundational（T005～T013）**：依賴 Setup；**阻擋所有故事**。測試檔 T005、T007、T009、T011、T013 可平行；實作 T006→（T008、T010 可平行）→T012。
- **US2（T014～T018）**：依賴 Foundational（`SubstackStore`、`substack_import.py` 骨架）。
- **US1（T019～T028）**：依賴 Foundational＋US2 的 `substack_html.classify`／`html_to_text`（T015）。
- **US3（T029～T034）**：依賴 US1（步驟 5 接在主流程後、摘要計數）。
- **US4（T035～T039）**：依賴 US1；與 US3 都改 `substack_import.py`／`test_substack_import.py`，**須循序**（建議 US3→US4，或 US4→US3 皆可，但不可同時）。
- **US5（T040～T045）**：依賴 US1；**T034、T038、T041 都改 `substack_config.py`、T033、T037、T040 都改 `test_substack_config.py`，同檔不可平行，須循序**（US3→US4→US5 的設定部分依序做）；`substack_import.py` 部分（T042～T045）同樣循序。
- **US6（T046～T050）**：依賴 Foundational＋US2（有效完整度）＋US3（`downloaded` 圖片狀態）；`substack_transcribe.py` 為獨立檔，可在 US3 完成後與 US4／US5 平行；T048（攔截法可行性）必須先於 T049。
- **US7（T051～T058）**：依賴 Foundational（`substack.db` schema）＋US1（`run`／`poll_log` 實際內容）；只改兩個既有檔，可與 US3～US6 平行。
- **Polish（T059～T074）**：T059～T066 依賴全部故事完成（T065 推送與開 PR 須 PO 當下確認，T066 驗收在其後）；T067～T074 依賴 T066 驗收 PASS，且依編號順序執行（部署 → 設定 → 首跑 → XPC 實測 → 安裝 → 隔天驗證 → 轉寫試跑）。

### 依賴圖（簡化）

```text
Setup ─▶ Foundational ─▶ US2 ─▶ US1 ─┬─▶ US3 ─▶ US4 ─▶ US5（循序：設定檔與 import 同檔） ─┐
                                      │    └──▶ US6（T048→T049） ───────┤
                                      └─▶ US7 ──────────────────────────┤
                                                                         ▼
                                        Polish：plist/文件/回歸/GATE ─▶ 【PO】FR-013 → 部署 → 設定 → 首跑 → XPC 實測 → 安裝 → 隔天驗證 → 轉寫試跑
```

### 故事內規則

- 測試任務先於實作任務，且必須先看到失敗（守門型測試除外，已註明）。
- `substack_store.py` → `substack_html.py` → `substack_import.py` 的順序不可倒置。
- 每個故事結束跑 `test_substack_*.py` 全綠才進下一個。

## Parallel Examples

```text
# Foundational：五個測試檔同時寫
T005 tests/test_substack_store.py ｜ T007 tests/test_substack_config.py ｜ T009 tests/test_substack_feed.py ｜ T011 tests/test_substack_import.py ｜ T013 tests/test_substack_isolation.py

# US2：兩個測試檔同時寫
T014 tests/test_substack_classify.py ｜ T016 tests/test_substack_reclassify.py

# US1 完成後可同時開兩條線（不同檔案）
線 A：T029→T030 substack_images.py（US3）
線 B：T051→T052→T053→T054→T055→T056→T057 backup_databases.py／check_scheduled_jobs.py（US7）
（US5 的 T040～T041 與 US3／US4 的 `substack_config.py`／`test_substack_config.py` 任務同檔，不平行，故不列為獨立線）

# US3 完成後
T046→T047 substack_transcribe.py（US6） 與 T035→T036（US4，substack_import.py）平行
```

## Implementation Strategy

### MVP（US2＋US1）

1. Phase 1～2 → Phase 3（US2）→ Phase 4（US1）。
2. **停下驗收**：在 `poc/data-test-substack/` 以假 HTTP 完整驗證首次 14 天窗、去重、分類、逐篇通知、排程日、預算、T-B、外洩掃描。
3. MVP **只在測試資料目錄驗收，不上線**：它沒有圖片下載、細緻告警、最小間隔守衛與備份健檢。

### 增量

4. US3（圖片）→ US4（被擋與告警策略）→ US5（追蹤清單、間隔、追補）→ 每步跑全套。
5. US7（備份、健檢）可在 US1 後任何時候平行做；**正式上線的最低組合建議＝US1～US5＋US7**（FR-004 間隔守衛、FR-032 告警、FR-029 備份是對站方禮貌與資料安全的前提）。
6. US6（手動轉寫）可最後做；其真實試跑（T074）在上線穩定後由 PO 擇時進行。
7. Polish：plist、文件、回歸、獨立驗收 → PO 確認的上線序列。

### 各故事獨立測試準則

| 故事 | 獨立測試（自動化） | 對應 V／SC |
|---|---|---|
| US1 | 空庫首跑只存 14 天內、重跑不增、新文章存入並逐篇通知（無連結；N 類逐篇通知附一次性提醒、摘要不附）、假時鐘六個邊界、預算強制中止 | V1、V10、V14、V15；SC-001～SC-003、SC-014、SC-015 |
| US2 | 結構樣本逐篇分類、不確定全為 P、不以長度判斷；N 類不存內文；重判歷史保留、原內容不變、零網路零模型（N→F 內文由原始內容產生） | V2、V12；SC-006、SC-012、SC-015 |
| US3 | 連續失敗 3 次放棄、重試、白名單外零請求、`add-image-host` 後可下載 | V3、V13；SC-008、SC-013 |
| US4 | A 被擋 B 照常、兩種告警策略、磁碟滿中止無半寫入 | V4；SC-007、SC-011 |
| US5 | 新增／停用生效、間隔跳過不告警、下限 10 分鐘、重新啟用 14 天窗、追補逐篇通知與「feed 已不提供」提示 | — ；FR-002、FR-004、FR-008 |
| US6 | 兩段式確認碼、`XPC_SERVICE_NAME` 五種值、選取規則、撞限停止、直接讀庫可查、T-C 全程未開 `articles.db` | V16；SC-009、SC-004 |
| US7 | 三個健檢項目輸出與禁字掃描、備份產物、token 間隔提醒且不改 plist、010 既有測試零差異 | V8、V9；SC-010 |

## 任務統計

| 階段 | 任務範圍 | 任務數 |
|---|---|---|
| Phase 1 Setup | T001～T004 | 4 |
| Phase 2 Foundational | T005～T013 | 9 |
| Phase 3 User Story 2（P1） | T014～T018 | 5 |
| Phase 4 User Story 1（P1） | T019～T028 | 10 |
| Phase 5 User Story 3（P2） | T029～T034 | 6 |
| Phase 6 User Story 4（P2） | T035～T039 | 5 |
| Phase 7 User Story 5（P2） | T040～T045 | 6 |
| Phase 8 User Story 6（P3） | T046～T050 | 5 |
| Phase 9 User Story 7（P3） | T051～T058 | 8 |
| Phase 10 Polish | T059～T074 | 16（其中【須 PO 當下確認】9 個、【GATE】1 個） |
| **合計** | | **74** |
