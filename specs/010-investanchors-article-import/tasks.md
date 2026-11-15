# Tasks: 定錨產業筆記文章自動匯入

**Input**: `specs/010-investanchors-article-import/`（spec.md、plan.md、research.md、data-model.md、contracts/cli.md、contracts/mcp-tools.md、quickstart.md）
**Prerequisites**: plan.md、spec.md 皆已定稿（主對話審查通過，2026-11-15）
**Tests**: 本功能要求測試（低頻上限、登出驗證、不外洩、工具數守門等守門測試是需求的一部分）。每個實作任務都附自己的測試，測試與實作同一任務完成。
**Organization**: 依 spec 四個 User Story 分階段：基礎 → US1（P1，可獨立交付）→ US2 → US3（程式）→ US4 → 上線 → 上線後（轉寫啟用與驗證期）。**任務編號順序就是執行順序**（speckit-implement 依編號執行）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行（不同檔案、無未完成的相依）
- **[US#]**：所屬 User Story（Setup／Foundational／上線階段不標）
- **[PO]**：需要 PO 親自動作（存金鑰、在場確認、抽查確認、同意、手動設定），agent 不得代做
- **[GATE]**：關卡任務（審查／驗收／真實網站執行／部署）
- 路徑慣例：程式在 `poc/kb-mcp/`，測試在 `poc/kb-mcp/tests/`，資料目錄守衛在 `app/`，排程在 `ops/launchd/`。Python 3.9 相容、僅標準庫（不得新增 Python 套件）。

## 通用規則（每個任務都適用）

1. **登入定錨網站的任務，以假網站測試為主**（`tests/fake_investanchors_site.py`，本機 http server）。**第一次對真實網站執行前，必須先提交推送、由主對話審查、再由 PO 在場同意**，且執行時 PO **只留手機一台登入、電腦瀏覽器已登出**（網站規定同帳號最多兩台；探查／排程的瀏覽器算一台）。每個真實網站執行任務都標 [GATE]，只執行一次、失敗不自行重跑、不改參數再試。
2. **不讀鑰匙圈內容**：只用 `keychain_secrets.get_secret()` 在程式內取用；排查只能用「存在與否」（`find-generic-password … >/dev/null && echo ok`），**禁止** `dump-keychain`、`-w`、`-g`。agent 不自行讀取鑰匙圈值。
3. **每個任務完成的證據**：該任務的測試實跑通過（貼指令與結果摘要）。整體回歸基準（2026-11-15）：`python3 -m unittest discover -s poc/kb-mcp/tests` 共 1407 個測試，**既有 5 個失敗／錯誤與本功能無關**（`test_us_stock_price_client.GetQuoteFallbackTest` 4 個、`test_flight_search.SampleDatesTest.test_covers_requested_number_of_months` 1 個）；不得新增失敗。
4. **日誌、通知、`last_error`、報告一律不含**帳密、cookie、登入狀態、CSRF token、追蹤 token、文章全文（FR-020、安全與隱私）。
5. **低頻是硬性要求**（FR-007）：每次 ≤5 篇、每日登入 ≤1 次、頁面間隔 30～90 秒、圖片下載間隔 5～15 秒、被擋後下一次執行延後 ≥1 天；放寬任一項須 PO 同意。
6. **推送與審查流程**：每個階段結束時提交、`git pull --rebase origin claude/admiring-ptolemy-1jaw79`、推送，並通知主對話審查（內容：commit、檔案、測試結果、需 PO 決定的事）。不建立或切換分支。
7. 改了 `poc/kb-mcp/*.py` 後，正式服務要重新部署才生效（`ops/deploy.sh`）；測試通過 ≠ 已上線。
8. **每日登入上限記在各自的資料庫裡**：手動對真實網站執行時用的是獨立測試資料目錄，與正式庫各算各的。**凡「正式排程已安裝」之後的任何手動真實網站執行**（例如 T062 的逐篇核對、日後的 `--backfill-since`），當天**必須先確認當晚排程不會再登入**（例如當天先停用該 launchd job，或其他方式佔用當日額度），並由 PO 知情同意，否則同一天會登入兩次。T023 與 T048 發生在部署（T055）之前，不受影響。
9. **手動對真實網站的測試一律使用獨立測試資料目錄 `poc/data-test-articles/`**（T002 確認已被 `.gitignore` 忽略），**不得**把 `--data-dir poc/data`（正式庫）寫進任何手動真實網站指令。
10. **轉寫由明確開關控制，預設關閉**（T038）：開關關閉時圖片照常下載、一律標 `untranscribed`、**完全不呼叫模型 API、也不讀取 `vision-api-key`**。不得用「鑰匙圈有沒有金鑰」當開關。

## 已完成（不要重列為待辦）

- [x] D01 Phase 0 探查工具與測試：`poc/kb-mcp/article_probe.py`、`poc/kb-mcp/scraper/investanchors_scraper.js`（probe 模式：登入、四段式伺服器端登出並驗證、被擋偵測、SIGTERM／SIGINT／SIGHUP 先登出再結束、登入表單範圍防呆）、`poc/kb-mcp/scraper/site_util.js`、`poc/kb-mcp/tests/test_article_probe.py`（45 個測試，含本機假網站端到端）— commits `6217c60`、`d253c72`、`55dbe04`、`568acae`、`bdf0575`、`f1a2d76`
- [x] D02 `poc/kb-mcp/keychain_secrets.py` 的 service 擴充：`INVESTANCHORS_SERVICE="stnd-investanchors"`、帳號 `email`／`password`／`vision-api-key`、per-service 白名單（009 預設行為不變）— commit `6217c60`
- [x] D03 Phase 0 探查本身：兩次站台探查（2026-11-15，PO 在場、手機一台登入）＋一次純信箱檢查，結果回填 `research.md` R0 實測表 — commits `9c7d83c`（回填）、`4cc2bca`（信只當觸發／核對頻率定案）
- [x] D04 規劃文件定稿：plan.md、research.md（R0～R12）、data-model.md、contracts/、quickstart.md、spec.md 修訂 — commits `4cc2bca` 及前序

> **重用要求**：scraper 的登入／登出／被擋偵測請重用 D01 已驗證的寫法（T011 抽成共用模組），不要重寫一套。

---

## Phase 1: Setup

- [x] T001 將 `tests/test_article_probe.py` 內的 `FakeSite` 抽成共用模組 `poc/kb-mcp/tests/fake_investanchors_site.py`（`test_article_probe.py` 改為 import，45 個探查測試行為不變仍全綠），並擴充：可設定每頁文章數、置頂項（跨頁重複）、文章頁內文結構（有圖／無圖／缺 `div#inves_content`／內文過短）、清單項目日期與 14 位數 ID（前 13 位為 epoch 毫秒）、被擋行為（403／逾時）、登出模式（沿用現有四種）、請求紀錄供斷言。驗收：`python3 -m unittest discover -s poc/kb-mcp/tests -p "test_article_probe.py"` 45 個全過。
- [x] T002 [P] 確認 `poc/data/articles.db`、`poc/data/articles_images/`、`poc/data/articles_probe/` 與**手動真實網站測試用的 `poc/data-test-articles/`** 都被 `.gitignore` 忽略（`git check-ignore -v` 逐一驗證，貼輸出；現有規則只有 `poc/data/` 與 `poc/data-test/`，`poc/data-test-articles/` 預期缺漏，須補規則並再驗證）。

---

## Phase 2: Foundational（阻擋所有 User Story）

**目的**：獨立資料庫、防呆工具、低頻守衛、不外洩工具、共用 scraper session。完成前不得開始任何 User Story。

- [x] T003 [P] 建立 `poc/kb-mcp/article_id_time.py` 與 `poc/kb-mcp/tests/test_article_id_time.py`：由文章 ID 推建立時間（research R11）——14 位數取前 13 位為 epoch 毫秒；換算時間早於 2020-01-01 或晚於「現在＋1 天」、ID 非 14 位數或非純數字 → `id_time_ok=0`（時間為 None）；`is_before_cutoff(id, cutoff_ms, margin_days=14)` 只在 `id_time_ok=1` 且 `id_ms < cutoff_ms − 14 天` 時回 True，**`id_time_ok=0` 一律回 False（不得判為早於截止日）**。測試涵蓋：樣本 ID（14 位、公告 13 位 `1612580077558`）、邊界日、非數字、過大／過小、餘裕邊界（恰好 14 天）。對應 spec 驗收（f）。
- [x] T004 建立 `poc/kb-mcp/article_store.py` 的 `ArticleStore` 骨架與 schema，以及 `poc/kb-mcp/tests/test_article_store.py`：`articles.db`（`DB_FILENAME="articles.db"`），比照 `flight_store.py`：`__init__(data_dir)` → `abspath`／`makedirs` → `sqlite3.connect(check_same_thread=False)` → `row_factory=Row` → `executescript(SCHEMA)`（全部 `CREATE TABLE IF NOT EXISTS`），**建構子不得寫入任何資料列**（2026-08-22 教訓，測試要斷言建構後各表筆數為 0）。表依 data-model.md：`article`（含 `id_time_ms`、`id_time_ok`、`pinned`、`status` 含 `deferred`）、`article_image`（`UNIQUE(article_id, seq)`）、`mail_clue`（`message_id`、`mail_date`、`seen_at`、`processed`；**無 article_id／title**）、`backfill_state`（單列，含 `cutoff_date`／`cutoff_ms`）、`import_runs`、`alert_log`，**另加 `setting`（`key TEXT PRIMARY KEY`、`value TEXT`；存轉寫開關，T038 使用）**，並同步 `data-model.md` 加一小段 `setting` 說明。**不提供任何 delete 方法**。獨立 `tempfile` data-dir 測試。
- [x] T005 在 `poc/kb-mcp/article_store.py` 實作文章方法並補測試（`tests/test_article_store.py`）：`upsert_discovered(article_id, url, title, list_date, via, pinned)`（URL 須符合 `^https://(www\.)?investanchors\.com/user/vip_contents/\d+$`；已 `fetched` 的文章再被看到 → 無動作、不覆寫、不重複，FR-003）、`mark_fetched(article_id, body, published_at)`（body 長度 < 下限 200 字 → 拒絕，維持原狀態，FR-013 不寫殘缺全文）、`mark_failed(article_id, error)`（`attempts+1`；`last_error` 經 T010 的脫敏函式；達 3 → `abandoned`）、`mark_deferred`、`mark_skipped`（公告）、`reset_abandoned`、`list_pending(limit)`（`discovered`＋`failed` 且 attempts<3，新文章優先）、`known_ids()`、`set_pinned`。狀態機測試對照 data-model.md「狀態機」每條邊，**含 fetched 不可再被改寫／abandoned 只能手動重置**。
- [x] T006 在 `poc/kb-mcp/article_store.py` 實作圖片、通知信線索、回補進度、設定方法並補測試：`add_image(article_id, seq, src_url)`、`set_image_file(...)`（下載失敗保留 NULL 供下次補抓）、`set_transcription(...)`（`transcription` 只存內容、無標示；`untranscribed` 時必為 NULL，FR-017）、`add_mail_clue(message_id, mail_date)`（同 Message-ID 不重複）、`unprocessed_mail_clues()`、`mark_mail_processed(...)`、`get_backfill_state()`／`set_backfill_state(...)`（`cutoff_date`／`cutoff_ms` 啟動後固定，只能經 T044 的放寬路徑變更）、`get_setting(key, default)`／`set_setting(key, value)`。
- [x] T007 在 `poc/kb-mcp/article_store.py` 實作執行紀錄與去重通知方法並補測試：`start_run(trigger)`、`finish_run(run_id, logged_in, attempted, fetched, result, logged_out, blocked_until)`、`logins_today(now)`（以台北日期計）、`blocked_until()`、`last_weekly_check()`、`unverified_logout_runs()`、`alert_once(kind, key, day)`（同 kind＋key 同日只通知一次，比照 `statement_alerts`／`alert_once`）。測試涵蓋跨日、時區邊界（23:00 與 00:30）、`logged_out=0` 查詢。

- [x] T008 [P] 建立 `app/article_deps.py` 與 `app/tests/test_article_deps.py`：資料目錄守衛，**複製** `app/us_stock_deps.py` 的邏輯（`ALPHAVIBE_DATA_DIR` 必須明確設定、未設定拒絕啟動、指向正式路徑需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`、yield 型 dependency），不 import 對方。測試涵蓋三種情形（未設定、正式路徑無旗標、獨立測試目錄）。
- [x] T009 建立 `poc/kb-mcp/investanchors_limits.py` 與 `poc/kb-mcp/tests/test_investanchors_limits.py`（spec 驗收（a））：常數 `MAX_ARTICLES_PER_RUN=5`、`MAX_LOGINS_PER_DAY=1`、`DELAY_RANGE=(30,90)`（秒）、`IMAGE_DELAY_RANGE=(5,15)`、`MAX_ATTEMPTS_PER_ARTICLE=3`、`BLOCK_BACKOFF_DAYS=1`、`MAX_LIST_PAGES=3`，註解寫明「放寬須 PO 同意」；`LimitGuard(store, now)`：`may_login()`（今日已登入 ≥1 次或 `blocked_until` 未到 → 拒絕並回原因）、`cap_for_run(requested)`（只能降低、不得超過 5）、`delay_seconds(rng)`（落在區間內）、`block_until(now)`（+1 天）。測試：第二次登入被拒、被擋後隔日前被拒隔日後放行、`--max-articles 99` 被壓回 5、間隔取樣不低於 30 秒、拒絕時**不觸發任何登入**（以假 scraper 計數斷言為 0）。依賴 T007。
- [x] T010 [P] 建立 `poc/kb-mcp/investanchors_redact.py` 與 `poc/kb-mcp/tests/test_investanchors_redact.py`（spec 驗收（c）的工具層）：`safe_error(exc_or_text, secrets)` 把帳密、cookie、`authenticity_token`／CSRF、`/c/<token>` 追蹤路徑、長字串（>200 字，疑似內文）一律遮蔽；`assert_clean(text, secrets)` 供其他測試重用。測試涵蓋：密碼出現在例外訊息、cookie 標頭、`sid=...`、長內文、追蹤 token 都被遮蔽。
- [x] T011 將 `poc/kb-mcp/scraper/investanchors_scraper.js` 的探查已驗證寫法抽成共用模組 `poc/kb-mcp/scraper/investanchors_session.js`：`launchSession(cfg)`（全新 context、不持久化 profile、`handleSIGINT/SIGTERM/SIGHUP:false`）、`go()`（導覽計數、上限、禮貌間隔、被擋偵測：403／429／導向非本站／連續 2 次逾時）、`submitLogin()`（第一個可見密碼欄位所屬 form、像註冊表單即 `ambiguous_login_form`）、`runLogoutFlow()`（四段式＋每步驗證）、`ensureLogout()`／訊號處理器。`investanchors_scraper.js` 的 probe 模式改為呼叫此模組，**行為不變**：`python3 -m unittest discover -s poc/kb-mcp/tests -p "test_article_probe.py"` 45 個須全過（含 SIGTERM 與隱藏選單 DELETE 的端到端）。這是後續 `import` 模式的共同基礎，**不得重寫第二套登入／登出**。

**Checkpoint**：基礎完成——ArticleStore、防呆、低頻守衛、脫敏、共用 session 皆通過測試。

---

## Phase 3: User Story 1 — 新文章自動進文章庫（P1，MVP）

**目標**：信箱有新信（或每週核對日）時代 PO 登入、讀清單、抓所有未入庫文章、登出並驗證、Telegram 通知；其餘時候不登入。

**獨立驗收**：假網站＋假信箱＋假 Telegram 下跑一次：文章庫出現該篇（標題、日期、網址、全文、圖片）、假網站端無殘留登入狀態、收到含標題與連結的通知；立刻再跑一次新增 0 篇；無新信且非核對日時假網站的登入請求為 0。

- [x] T012 [P] [US1] 建立 `poc/kb-mcp/investanchors_mailbox.py` 與 `poc/kb-mcp/tests/test_investanchors_mailbox.py`：`fetch_mail_clues(address, app_password, days, imap_factory=None)` → `[{message_id, mail_date}]`，沿用 `statement_mailbox.py` 骨架（`IMAP4_SSL`、`select(readonly=True)`、`BODY.PEEK`、`X-GM-RAW "from:postmaster@mailer.investanchors.com newer_than:Nd"`，`_find_all_mail`／`_fetch_parts` 重用），**只取 Message-ID 與寄達時間（轉台北日期時間）**；寄件者不符一律略過；**不解析、不記錄信中連結與標題**。Gmail 憑證用 `stnd-statement-import` 的 `gmail-address`／`gmail-app-password`。測試用假 IMAP：唯讀且 `PEEK`、寄件者偽造被略過、回傳不含連結／標題（以 `json.dumps` 斷言）、Gmail 登入失敗拋 `MailboxError`、UTC 時間正確換台北日期。
- [x] T013 [US1] 在 `poc/kb-mcp/scraper/investanchors_scraper.js` 新增 `import` 模式的**清單讀取**（重用 T011 模組），stdin 契約見 contracts/cli.md §4：輸入 `known_ids`、`max_list_pages`（≤3）；讀清單第 1 頁，必要時往後翻到「一頁內非置頂、非公告項目全部在 `known_ids`」為止；輸出 JSONL `list_item {article_id, title(連結文字), date, is_announcement, read_state}`，並在跨頁出現的項目上標 `pinned:true`（置頂＝同一 ID 在相鄰頁重複出現）；不依賴清單位置；公告（標題以「【公告】」開頭）標記但不開啟。測試用 T001 的假網站（`tests/test_investanchors_scraper_import.py`）：置頂項去重、全部已知時只讀 1 頁、`max_list_pages` 上限、清單日期不用於任何判斷。
- [x] T014 [US1] 在 `poc/kb-mcp/scraper/investanchors_scraper.js` 的 `import` 模式新增**文章擷取**（與 T013 同檔，接在其後）：對 Python 傳入的 `article_ids`（≤5，已由 `LimitGuard` 壓上限）逐篇開啟，篇間隔隨機 30～90 秒（`delay_ms` 由 Python 傳入，測試可縮短）；只取三樣：內文容器 `div#inves_content` 的文字、發布時間 `span.post_date`、內文容器內圖片 `src_url`（含順序）；標題**不**從文章頁取。取不到容器或內文長度 <200 字 → 輸出 `article_error {reason:"structure"}`，**不輸出殘缺內文**；逾時連續 2 次 → `blocked`；同次不重試失敗的篇。最後一定先伺服器端登出並驗證，再輸出 `summary {blocked, logged_out, logout_verified, counters}`。測試擴充 `test_investanchors_scraper_import.py`：缺容器、內文過短、有圖／無圖、被擋 403、逾時、結束後假網站 `sessions` 為空、SIGTERM 中途仍登出。
- [x] T015 [P] [US1] 建立 `poc/kb-mcp/article_images.py` 與 `poc/kb-mcp/tests/test_article_images.py`：`download_images(store, article_id, data_dir, sleeper, rng)` — 以 `urllib` **不帶 cookie** 下載（圖片網址不需登入，探查實測），存 `<data_dir>/articles_images/<article_id>/<seq>.<ext>`（副檔名只允許 png／jpg／jpeg／webp／gif；路徑不得含 `..`），每張之間隨機間隔 5～15 秒，單張失敗 → 該圖 `file_path` 留 NULL 並記錄、不影響文章（下次補抓）、檔案過大（>20MB）拒收。測試用本機 http server：成功／404／逾時／副檔名可疑／路徑穿越／間隔取樣範圍；下載不計入登入次數。
- [x] T016 [US1] 建立 `poc/kb-mcp/investanchors_import.py` 骨架與 `poc/kb-mcp/tests/test_investanchors_import.py`：argparse（`--data-dir`、`--dry-run`、`--force-weekly`、`--max-articles N`〔只能降低，上限 5〕，其餘旗標留給後續任務）、依賴注入點（`fetch_mail`、`run_scraper`、`download_images`、`transcribe`、`notifier`、`get_secret`、`now`、`sleeper`）、`main(argv)` 回傳 exit code（0 正常含無觸發／1 有失敗／2 因上限或退避拒絕）。流程到「決定觸發」為止：(1) `LimitGuard.may_login()` 拒絕 → 記一筆 `aborted_limit` 後結束且**不登入**；(2) 唯讀取信、寫入 `mail_clue`（失敗＝不因信觸發，連續失敗才通知）；(3) 觸發＝有未處理新信／週日且上次核對 ≥6 天前（或 `--force-weekly`）／回補未完成（US4 才會為真）；都沒有 → `trigger=none`、**不啟動 scraper**（SC-003）。`--dry-run`：只取信、列出觸發判斷，不登入、不寫入、不通知。測試：無觸發時 `run_scraper` 呼叫 0 次、每日第二次被拒、`blocked_until` 未到被拒、dry-run 零副作用、週日／非週日觸發判斷、信箱失敗不觸發抓取。
- [x] T017 [US1] 在 `investanchors_import.py` 實作「套用 scraper 結果」並補測試：把 `list_item` 寫入 store（重複不產生第二筆，FR-003；已 `fetched` 不重開；公告 → `skipped`，FR-004；置頂 → `pinned=1`、不得被當舊文）、待抓清單 = 清單上**所有未入庫 ID**（不論有無通知信）＋`failed` 且 attempts<3，**新文章優先於回補**、截止於每次 5 篇，其餘留待之後；`article` 事實 → `mark_fetched`／`add_image`；標題取清單連結文字；`id_time_ms`／`id_time_ok` 以 T003 計算寫入。測試對照 US1 驗收情境 1、3、4、5、7（情境 2 在 T016）。
- [x] T018 [US1] 在 `investanchors_import.py` 實作失敗處理並補測試（FR-011／012／013）：登入失敗（密碼錯／帳號停用）→ 當次中止、不重試、既有文章不變、通知；被擋 → 整次中止、`blocked_until=+1 天`、通知、**不反覆重試**；頁面結構改變／內文過短 → 該篇標失敗（`attempts+1`）、**不寫殘缺全文**、通知與失敗清單；單篇失敗**同次不重試**、下一次排程才試、累計 3 次 → `abandoned`＋通知；一篇失敗不影響其他篇；`last_error` 一律經 `safe_error`。測試涵蓋 spec Edge Cases 全部條目（單張圖片下載失敗 → 文章仍保存、圖標記缺）。
- [x] T019 [US1] 在 `investanchors_import.py` 實作登出強制與通知並補測試（spec 驗收（b））：每次執行結束（不論成敗，含例外與訊號）都要求 scraper 回報伺服器端登出已驗證；`import_runs.logged_out=1` 才算合格；**登出未驗證 → 立即 Telegram 通知**（文字：登入狀態可能殘留、PO 在自己裝置登出無法清除、勿再次執行、請回報），並寫 `logged_out=0`。新文章通知只含標題＋連結（FR-019），失敗通知依類別（登入失敗／帳號停用／被擋已延後／單篇放棄／結構改變／登出未驗證，FR-020），全部經 `alert_once` 同日去重；通知用既有 `notify.send_telegram`。測試：新文章通知不含內文、同日同類別不重複、登出未驗證必通知。
- [x] T020 [US1] 建立端到端測試 `poc/kb-mcp/tests/test_investanchors_import_e2e.py`（假網站＋真 scraper＋假信箱＋假 Telegram，無瀏覽器環境時 skip）：情境一 有新信 → 文章入庫、假網站 `sessions` 為空、收到含標題與連結的通知；情境二 立刻再跑 → 新增 0 篇、不重複開啟已入庫文章；情境三 無新信、非核對日 → 假網站請求紀錄**登入請求為 0**（SC-003）；情境四 清單有置頂與公告 → 公告不開啟、置頂不重複入庫；情境五 待抓 8 篇 → 只抓 5 篇、其餘下次；情境六 被擋 → 中止且 `blocked_until` 生效。
- [x] T021 [US1] 建立不外洩負向測試 `poc/kb-mcp/tests/test_investanchors_no_leak.py`（spec 驗收（c））：延伸 T020 的執行，收集 stdout／stderr、所有寫出的檔案、資料庫每個 TEXT 欄位（含 `last_error`）、全部假 Telegram 訊息，逐一以 `assert_clean` 斷言**不含**：測試密碼、假 cookie 值、CSRF token、`/c/<token>` 形態、文章全文（用一段獨特標記字串）。同時涵蓋登入失敗與被擋的失敗路徑。
- [x] T022 [GATE] [US1] 提交推送 T001～T021 並通知主對話審查（commits、檔案、測試結果、完整套件對照基準）。**審查通過前不得執行真實網站。**
- [x] T023 [GATE] [PO] [US1] 首次對真實網站執行（**PO 在場、電腦瀏覽器已登出、只留手機一台登入、在對話親自確認；主對話已審過**）：`python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data-test-articles --max-articles 1 --force-weekly`（**獨立測試資料目錄，不是正式庫**；`--force-weekly` 用來觸發）。只執行一次，不重跑；**空庫第一次執行會讀 3 頁清單**，把清單上約 45 篇登記為 `discovered`，但只抓 1 篇。結束後確認 `import_runs.logged_out=1`、文章庫 `fetched` 恰 1 篇（其餘為 `discovered`）、PO 手機仍在線、無 token／全文外洩（以 `assert_clean` 掃描器對真實輸出跑一次）；結果與下一步回報主對話。**結果（2026-11-15）**：exit 0、登入 1 次、讀 3 頁清單、fetched 1／discovered 44／skipped 1、logged_out=1、下載圖 1 張、外洩掃描 0 違規；PO 確認手機收到 1 則 Telegram（文章連結）、手機定錨仍在登入。此時正式排程尚未安裝（T055 之前），不受通用規則 8 影響。
- [x] T024 [GATE] [US1] 獨立驗收（全新 agent，非實作者）：對照 spec US1 驗收情境 1～7、FR-001～004／006～013／019～020、SC-003／004／006，**只給驗收條件與否決條件，不給實作推理**；任一條沒有證據 → 整體 FAIL。通過後 US1 才算可交付。

**Checkpoint**：US1 可獨立交付（MVP）。其後 US2～US4 不得破壞 US1 測試。

---

## Phase 4: User Story 2 — 在對話中搜尋與閱讀文章（P2）

**目標**：台股與美股兩個連接器都能以關鍵字搜尋已匯入的文章、讀單篇全文，且結果相同。

**獨立驗收**：文章庫有數篇文章時，從台股與美股連接器以同一關鍵字（含 2 字中文，如「環宇」）搜尋，得到相同清單（標題、日期、片段、原文網址），並可讀其中一篇全文與圖片資訊；查無結果時明確回覆。

- [x] T025 [US2] 在 `poc/kb-mcp/article_store.py` 實作 `search_articles(query, limit)` 與 `get_article(article_id)` 並補測試：**不用 FTS5**（research R6：trigram 搜不到 2 字中文詞），用 `LIKE` 掃描——查詢以空白切多個關鍵字、全部需出現（AND），範圍＝標題＋全文＋圖片轉寫文字，僅 `status='fetched'`；片段取首個命中處前後約 60 字並標明命中來源（內文／表格轉寫）；依發布日期新到舊；`limit` 預設 10、最大 30；`get_article` 找不到或非 `fetched` → 明確錯誤、不回殘缺內容。測試涵蓋 2 字中文詞（「環宇」「財測」）、英文 3 字（「EPS」）、多關鍵字 AND、僅出現在轉寫文字的數字、查無結果、`LIKE` 特殊字元（`%`、`_`）跳脫。
- [x] T026 [US2] 建立 `poc/kb-mcp/article_tools.py` 與 `poc/kb-mcp/tests/test_article_tools.py`：兩個共用格式化函式 `search_articles_text(store, query, limit)`、`get_article_text(store, article_id)`，輸出依 contracts/mcp-tools.md：每筆含標題｜發布日期｜**原文網址（必帶）**｜片段｜article_id；`get_article` 含全文、圖片清單 `#seq｜是否表格｜轉寫狀態｜原圖 src_url｜本機路徑`，**「機器轉寫，可能有誤，請以原圖為準」標示由輸出層加上**（資料庫不存），`untranscribed` 明寫「未轉寫」；唯讀、不觸發任何網站存取、不存在於庫就回錯誤而不去抓。台股與美股共用這一份，確保輸出一致。
- [x] T027 [US2] 在台股 MCP 註冊兩個工具：`poc/kb-mcp/server.py`（`TOOLS` 加 `search_articles`／`get_article` 的 schema，`call_tool` 加分派，資料目錄解析沿用該 server 既有方式開 `<data_dir>/articles.db`）與 `poc/kb-mcp/server_readonly.py`（`READONLY_TOOLS`＋`READONLY_TOOL_SCHEMAS` 加兩個）。工具名不得與既有工具衝突。
- [x] T028 [P] [US2] 在美股 MCP 註冊兩個工具：`poc/kb-mcp/us_stock_mcp_server.py`（`TOOLS`＋`call_tool`，台美刻意各自一份，見 `app/routers/mcp.py` 註解；資料目錄解析沿用美股 server 既有方式，開**同一個** `<data_dir>/articles.db`，不寫入 `us_stocks.db`）。依賴 T026；與 T027 不同檔，可平行。
- [x] T029 [US2] 更新工具數守門測試（spec 驗收（d））：`poc/kb-mcp/tests/test_pnl.py::test_tool_counts`（`len(server.TOOLS)` 48→50、`len(READONLY_TOOLS)` 29→31）；`poc/kb-mcp/tests/test_traceability.py::test_tools_list_has_forty_eight`（約 :252-261，改名為 `…_fifty`、docstring 註明 2026-11 新增 `search_articles`／`get_article`、`assertEqual(len(names), 50)`、預期工具名清單加兩項）；`poc/kb-mcp/tests/test_claude_ai_connector.py` 美股 `names == TOOLS` 的預期清單加兩項（並確認「美股不含 `get_holdings`」斷言仍成立）；`poc/kb-mcp/tests/test_us_stock_mcp_server.py` 若有工具數斷言一併更新。完整套件實跑，確認只有基準的 5 個既有失敗。
- [x] T030 [US2] 建立兩連接器一致性測試 `poc/kb-mcp/tests/test_article_connectors_parity.py`（spec 驗收（e））：同一個測試 `articles.db`、同一組關鍵字（中文 2 字、英文、多關鍵字、查無）、同一個 `get_article`，分別經台股 `server.call_tool` 與美股 `us_stock_mcp_server.call_tool` 呼叫，**輸出逐字相同**；且兩邊都不能寫入（無寫入工具、`articles.db` 開啟為唯讀查詢路徑）。
- [x] T031 [US2] 文件同步：更新根目錄 `CLAUDE.md`「常用查證點」的新增 MCP 工具同步清單（加入 `article_tools.py`、`articles.db` 由兩個 server 共讀、兩處守門測試），並在 `specs/010-investanchors-article-import/quickstart.md` 補「Mac 上 `~/.claude` 的 stock-researcher 白名單須由 PO 手動加入兩個工具」（列入 PO 待辦 T056）。
- [x] T032 [GATE] [US2] 提交推送 T025～T031 並通知主對話審查；通過後由全新 agent 獨立驗收 US2 驗收情境 1～4、FR-014／015、SC-008（只給驗收條件與否決條件）。

**Checkpoint**：US2 可獨立使用——對話中查得到 US1 已匯入的文章。

---

## Phase 5: User Story 3 — 表格裡的數字也讀得到（P3，程式開發；真實啟用在上線後）

**目標**：匯入時把內文圖（可能是很高的長圖）轉寫成文字存檔、可被搜尋；轉寫失敗標「未轉寫」、可事後補轉不需重抓網站。

**本階段的範圍**：只開發、審查、獨立驗收**程式**，一律使用**合成圖與假模型**；真實模型、PO 抽查與啟用在上線後（Phase 8 的 T058～T061），因為真實圖片要等回補累積。**轉寫由預設關閉的開關控制**（通用規則 10）。

**獨立驗收（程式層）**：開關打開時，匯入含財測表圖的文章，只出現在表格圖裡的個股代碼可搜到該文章，讀取時有「機器轉寫」標示與原圖資訊；轉寫失敗的圖標「未轉寫」且可 `--retranscribe` 補轉；開關關閉時不呼叫模型。

- [x] T033 [US3] 研究任務（**不需金鑰**）：對照官方文件確認模型 ID `claude-haiku-5-5` 存在且可用、Messages API 請求格式（圖片 base64 區塊、結構化輸出、`max_tokens` 與預設思考的關係、不得送非預設 temperature／top_p／top_k、`stop_reason` 為 `refusal`／`max_tokens` 的處理）、單張圖片的尺寸與 token 計算上限；結果寫回 `research.md` R5。若模型 ID 不存在或請求格式與假設不符，**回報主對話，不自行換模型**。
- [x] T034 [US3] 決定切片實作方式並寫回 `research.md` R5：Python 標準庫**無法解碼 PNG**，而 plan 規定不新增 Python 套件。候選：(a) Playwright canvas（Node，已是既有依賴，可 `getImageData` 偵測空白橫帶並輸出切片）；(b) macOS `sips`（系統內建，只能裁切、無法讀像素）；(c) Pillow（新增依賴，**須 PO 同意**）。優先 (a)；若選 (c) 必須先回報主對話請 PO 決定。
- [x] T035 [P] [US3] 建立切片模組與測試：`poc/kb-mcp/article_image_tiles.py`（Python 端規劃與合併邏輯）＋依 T034 結論的 Node 腳本（例 `poc/kb-mcp/scraper/image_tiler.js`）＋`poc/kb-mcp/tests/test_article_image_tiles.py`。原則（research R5）：依高度垂直切片、每片高約寬度的 0.6～0.8 倍；**相鄰切片重疊 ≥15% 且 ≥200px**；切點優先落在整列近乎同色的橫向空白帶；**切片數上限 8**，超過 → 該圖標 `untranscribed`（不縮小湊數）；原圖完整保留、切片只暫存不入庫；合併轉寫時依重疊區列文字去重。測試用合成圖（程式生成的長圖與表格圖）：2190×5195 切片數與重疊、切點避開文字列、超過上限回報、短圖不切。（spec 驗收（g））
- [x] T036 [US3] 建立 `poc/kb-mcp/article_transcribe.py` 與 `poc/kb-mcp/tests/test_article_transcribe.py`：`urllib` 呼叫視覺模型（不裝 SDK，理由見 research R5）；模型 ID 為模組常數 `TRANSCRIBE_MODEL`（預設依 T033 結論）；金鑰用 `keychain_secrets.get_secret("vision-api-key", service=INVESTANCHORS_SERVICE)`，**絕不寫入日誌／例外**；提示詞：只轉寫可見數字與文字、看不清楚寫 `?`、回結構化 `{is_table, text}`；多切片時附「上一片表頭與最後 2 列」上下文並要求略過重複列；`stop_reason` 為 `refusal`／`max_tokens`、缺金鑰、額度不足、HTTP 錯誤、逾時 → 該圖 `untranscribed`（**不以空白或猜測值充數**，FR-017）。測試用**本機假 HTTP server**：成功、refusal、max_tokens、401、429、逾時、金鑰不外洩（錯誤訊息／日誌掃描）、多切片合併去重。
- [x] T037 [US3] 在 `poc/kb-mcp/investanchors_import.py` 把轉寫接進匯入流程並實作 `--retranscribe`（FR-016／017）：圖片下載後逐圖轉寫（失敗不影響文章）、記錄 `transcribed_model`；`--retranscribe` **只讀本機圖片檔、不啟動 scraper、不登入網站**（可補做未轉寫、或換模型後重轉）。測試：轉寫失敗時文章與原圖照常保存、之後 `--retranscribe` 補成功；`--retranscribe` 執行時 `run_scraper` 呼叫次數為 0。**轉寫步驟與 `--retranscribe` 都受 T038 的開關控制。**
- [x] T038 [US3] 新增**轉寫啟用開關**（預設關閉）並補測試：開關存在 `articles.db` 的 `setting` 表（`transcribe_enabled`，無此列＝關），由 `investanchors_import.py --enable-transcription`／`--disable-transcription` 明確切換（冪等、印出目前狀態、只改該設定，不做其他事）；**不得用鑰匙圈有沒有 `vision-api-key` 當開關**。開關關閉時：圖片照常下載、`transcription_status` 一律 `untranscribed`、**不呼叫模型 API、也不呼叫 `get_secret("vision-api-key")`**；`--retranscribe` 在關閉時拒絕並回 exit 2（訊息寫明「轉寫開關未開」）。`--transcribe-sample`（T040）是唯一在開關關閉時可呼叫模型的路徑，且**不寫入資料庫**。測試（假 HTTP 模型 server 計數、假鑰匙圈 runner 計數）：(1) 預設關閉＋鑰匙圈**有**金鑰 → 匯入含圖文章後模型請求數 0、`get_secret("vision-api-key")` 呼叫數 0、圖標 `untranscribed`；(2) 打開後請求數 >0 且轉寫寫入；(3) 再關閉後新圖不轉寫；(4) 關閉時 `--retranscribe` 被拒；(5) 切換後重新建立 `ArticleStore` 仍保持狀態。同步 `contracts/cli.md` 加三個旗標與預設關閉說明、`research.md` R5 加一句。
- [x] T039 [US3] 搜尋與輸出整合測試 `poc/kb-mcp/tests/test_article_transcription_search.py`：只出現在表格轉寫文字的個股代碼／數字可搜到該文章（命中來源標「表格轉寫」）；`get_article` 輸出含「機器轉寫」標示與原圖 `src_url`；資料庫 `transcription` 欄不含標示字樣（避免 `LIKE` 被標示命中所有文章）；`untranscribed` 明寫「未轉寫」。（FR-016、US3 情境 1～3）
- [x] T040 [US3] 建立抽查工具：在 `poc/kb-mcp/investanchors_import.py` 加 `--transcribe-sample N`（只讀本機已下載的圖、不登入網站；隨機抽 N 張**且必須至少含 1 張長圖**，若庫內累積的圖不足 N 張或無長圖 → 回報不足與目前數量，不勉強）。「長圖」定義：高/寬 ≥ 1.5 且高度 ≥ 2000px；尺寸用標準庫讀 PNG IHDR／JPEG SOF（不需解碼）。**只轉寫抽樣的圖**，結果只寫進 `poc/data/articles_probe/transcribe-sample-<時間>.md`（gitignore；原圖路徑＋轉寫文字供 PO 逐格比對），**不寫入資料庫**（開關仍關閉時 DB 內仍全是 `untranscribed`）。測試（假模型）：抽樣含長圖、庫內不足時回報不足、不登入、不寫 DB、輸出檔不含金鑰。
- [x] T041 [GATE] [US3] 提交推送 T033～T040 並通知主對話審查；通過後由全新 agent 獨立驗收 US3 **程式層**驗收情境 1～3、FR-016／017／018 的程式行為（開關預設關閉、關閉時零 API 呼叫、失敗標未轉寫、可補轉、切片規則）、spec 驗收（g）（只給驗收條件與否決條件）。**SC-007 的真實準確度由上線後 T059 的 PO 抽查負責，不在本任務。**

**Checkpoint**：US3 程式完成並通過審查／驗收；真實轉寫尚未啟用（開關關閉）。

---

## Phase 6: User Story 4 — 最近半年的歷史文章補齊（P4）

**目標**：以小批次分散多天補齊「建立時間在半年內」的文章（約 100 篇、每天 5 篇約 20 天），可中斷續跑，補完即停；更早的標「延後」。

**獨立驗收**：啟動回補後多次（模擬多天）執行：每次不超過 5 篇、中斷後從未完成處接續、置頂文章不被誤判為舊文、完成後與網站「總覽」中半年內文章逐篇核對無缺漏無重複、之後回補不再執行。

- [x] T042 [US4] 在 `poc/kb-mcp/investanchors_import.py` 實作回補核心並補測試（research R11、spec 驗收（f））：首次啟動把 `cutoff_date`／`cutoff_ms`（啟動日往前六個月）寫入 `backfill_state` 後固定；**半年截止只用 T003 的 ID 時間**（餘裕 14 天），不使用清單日期；`id_time_ok=0` 的文章**一律不得 `deferred`**、照常處理並累計，**累計超過 3 篇 → 通知 PO**（規律可能失效）；置頂項不得跳過；早於截止日者記 `deferred`（只存 ID、標題、清單日期，不開啟）；停止規則：一頁內所有「非置頂、非公告」項目的 ID 時間都早於 `cutoff−14 天` 才不再往舊翻；`next_cursor` 續跑；新文章優先於回補、共用每日 5 篇額度；完成 → `completed=1` 且之後不再觸發。測試涵蓋：置頂 4 篇清單日期顯示 2021 但 ID 為近期 → 照常抓；非 14 位 ID → 不跳過並記錄；換算時間不合理 → 不跳過；第 4 篇異常 ID → 通知；中斷（下一次）接續不重抓；完成後 `trigger` 不再因回補為真。
- [x] T043 [US4] 在 scraper `import` 模式補上回補用的清單翻頁（`poc/kb-mcp/scraper/investanchors_scraper.js`）：由 Python 傳入 `cutoff_ms`、`resume_cursor`（頁碼）與 `stop_rule`，每次登入翻頁數受 `max_list_pages` 約束（回補單次最多 3 頁），輸出每頁項目與是否已達停止條件；跨頁置頂去重沿用 T013。測試用假網站（多頁、置頂、跨截止日）：停在正確的頁、不往更舊翻、不超過頁數上限。
- [x] T044 [US4] 實作 `--backfill-since <YYYY-MM-DD>`（PO 要求補抓更早文章；contracts/cli.md §1）並補測試：只能往前放寬（新日期早於現有截止日，否則拒絕）、`cutoff_date`／`cutoff_ms` 更新、`completed` 重設為 0、ID 時間落在新舊截止日之間的 `deferred` 轉回 `discovered`、仍受每日 5 篇上限；放寬範圍須 PO 同意（參數說明與拒絕訊息要寫明）。
- [ ] T045 [P] [US4] 建立 `poc/kb-mcp/article_reconcile.py` 與 `poc/kb-mcp/tests/test_article_reconcile.py`（SC-001）：唯讀，讀「總覽」清單到「整頁都早於截止日」為止（同樣受頁數上限與間隔約束，可分多次），與 `article`（排除公告）中建立時間在半年內者逐篇比對，輸出缺漏／重複清單；早於截止日者只確認為 `deferred`；不寫入 `article`。測試用假網站：缺漏、重複、置頂、延後各一例。
- [ ] T046 [US4] 建立多日回補模擬測試 `poc/kb-mcp/tests/test_investanchors_backfill_e2e.py`（假網站＋假時鐘，每「天」跑一次）：約 12 篇半年內＋6 篇更早＋置頂 4 篇 → 每日 ≤5 篇、第二天中斷後第三天接續、更早的只有 `deferred`、完成後 `completed=1`、再跑不登入；`article_reconcile` 回報 0 缺漏 0 重複。
- [ ] T047 [GATE] [US4] 提交推送 T042～T046 並通知主對話審查；通過後由全新 agent 獨立驗收 US4 驗收情境 1～5、FR-005、SC-001 的程式行為（含置頂與 ID 防呆的否決條件；只給驗收條件與否決條件）。**審查與驗收通過前不得執行下一個任務的真實網站手動回補。**
- [ ] T048 [GATE] [PO] [US4] 對真實網站手動試跑一次回補（**PO 在場、電腦瀏覽器已登出、只留手機一台登入、在對話親自確認；T047 已審過**）：`python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data-test-articles --max-articles 5`（**獨立測試資料目錄 `poc/data-test-articles/`，不是正式庫**；此時回補在該測試庫首次啟動）。只執行一次、不重跑；確認置頂文章被正確處理、`deferred` 標記、`logged_out=1`、無外洩；結果回報主對話。此任務在部署（T055）之前，**正式排程尚未安裝，不受通用規則 8 影響**；若日後有人在排程安裝後重做此類手動回補，須先依規則 8 處理當日額度。

**Checkpoint**：US4 完成——半年回補可中斷續跑、完成即停。

---

## Phase 7: 上線（部署前準備、驗收、部署）

**目的**：排程、健康檢查、文件、全面驗收、主對話最後審查、部署。**順序即依賴**：部署（T055）一定在審查（T054）之後。

- [ ] T049 [P] 建立 `ops/launchd/com.alphavibe.investanchorsimport.plist`：樣式同 `com.alphavibe.statementimport.plist`（`/usr/bin/python3 /Users/stander/My_project/AlphaVibe-prod/poc/kb-mcp/investanchors_import.py --data-dir …/AlphaVibe-prod/poc/data`、`WorkingDirectory`、PATH 含 `/opt/homebrew/bin`、log 寫 `~/Library/Logs/alphavibe-investanchors*.log`、**無** `RunAtLoad`／`KeepAlive`、`StartCalendarInterval` 每晚 **23:00**（PO 決定；不與既有 02:00／03:30／03:45／04:00／06:00／07:45／09:30／17:00／20:15／23:15／週一 10:00 相同）。以 `plutil -lint` 驗證語法；測試：讀 plist 斷言時間、無 RunAtLoad、log 路徑。
- [ ] T050 [P] 在 `poc/kb-mcp/check_scheduled_jobs.py` 新增 `check_investanchors_import(data_dir)` 並補 `poc/kb-mcp/tests/test_check_scheduled_jobs.py`（比照 `check_statement_import`）：讀 `import_runs`，標出 `logged_out=0` 的執行（嚴重）、超過 N 天沒有任何執行紀錄、`blocked_until` 仍生效、`abandoned` 文章數、`id_time_ok=0` 累計、轉寫開關狀態。測試涵蓋各狀態的輸出。
- [ ] T051 [P] 文件收尾：更新根目錄 `CLAUDE.md`（SPECKIT 區塊改指向本功能現況與接手指引、新增教訓紀錄：置頂項清單日期不可靠、ID＝建立時間的觀察與防呆、Playwright 預設訊號處理會先關瀏覽器、通知信連結是追蹤轉址不可跟隨、報告不得含 token、開文章會改已讀、轉寫由預設關閉的開關控制）、`specs/010-.../quickstart.md` 回填實測與上線步驟，並在 quickstart 加**唯讀查詢範例**（`sqlite3 -readonly poc/data/articles.db "select …"`：累積圖片張數、長圖張數〔以抽查工具判定〕、`import_runs` 摘要）供 T057 使用。`docs/spec-intake/` 不動（由主對話維護）。
- [ ] T052 完整回歸：`python3 -m unittest discover -s poc/kb-mcp/tests` 與 `ALPHAVIBE_DATA_DIR=<獨立測試庫> .venv/bin/python3 -m app.tests.test_smoke`（依 CLAUDE.md 的重建步驟），結果對照通用規則 3 的基準：**只允許既有 5 個失敗／錯誤**，貼總數與失敗名單。
- [ ] T053 [GATE] 全面獨立驗收（全新 agent，非實作者）：對照 spec **全部** User Story 驗收情境（US3 為程式層）、FR-001～020、SC-001～008（SC-001／SC-007 的真實驗證在上線後，此處驗程式行為）、Edge Cases；只給驗收條件與否決條件（含「測試其實沒跑」「宣稱處理 X 但檔案裡找不到」「轉寫開關預設不是關閉」），不給實作過程。FAIL 的條目修好後重驗。
- [ ] T054 [GATE] 提交推送並通知主對話做**上線前最後審查**。通過後才可進入 T055。
- [ ] T055 [GATE] [PO] 部署與安裝排程：依序提交推送 → 備份（`ops/deploy.sh` 慣例）→ 部署到 `AlphaVibe-prod`（改過 `poc/kb-mcp/*.py` 與 `app/` 需重啟對應正式服務，確認 MCP 連接器已套用）→ 安裝 plist（`launchctl bootstrap`）→ 用 launchd 實跑驗證一次。**部署、安裝與實跑需 PO 在場同意**（涉及正式資料與常駐設定）；**正式庫的轉寫開關維持預設關閉**；回報實際結果，不假設已上線。依賴 T049、T050、T054。
- [ ] T056 [PO] **PO 待辦**：在 Mac 的 `~/.claude` stock-researcher 白名單手動加入 `search_articles`／`get_article`（不在 repo，agent 不修改 `~/.claude` 設定）。依賴 T055。

---

## Phase 8: 上線後——回補累積、轉寫啟用與驗證期

**目的**：部署後回補隨排程自動開始（每天最多 5 篇），圖片逐漸累積；累積到 ≥10 張且含長圖後，才由 PO 存金鑰、抽查、通過後打開轉寫開關並補轉積壓。**轉寫在這之前一律關閉。**

- [ ] T057 [PO] 部署後確認回補已開始並觀察圖片累積：用 quickstart 的唯讀查詢（T051）每隔幾天檢視 `import_runs`（登入次數、`logged_out`、是否被擋）與已下載圖片張數；回補約 20 天完成、圖片隨之累積。**目標：≥10 張且含 ≥1 張長圖**（`--transcribe-sample` 會回報目前數量與是否含長圖）。未達標前不進下一步。依賴 T055。
- [ ] T058 [PO] **PO 待辦**：累積達標後，把視覺模型 API 金鑰存進鑰匙圈（`security add-generic-password -U -s stnd-investanchors -a vision-api-key -w`，`-a` 後是固定名稱、`-w` 後不接任何東西、互動輸入）；用「存在與否」指令驗證。agent 不讀取其值。**存金鑰不會啟動轉寫**（開關仍關閉，通用規則 10）。依賴 T057。
- [ ] T059 [GATE] [PO] 上線前抽查（spec US3 情境 4、FR-018／SC-007）：在**正式庫**（唯讀圖片、不登入網站）跑 `python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data --transcribe-sample 10`（只轉寫抽樣的 10 張，**須含長圖**；結果只寫入 `poc/data/articles_probe/transcribe-sample-<時間>.md`，不寫 DB；會產生少量 API 費用，**PO 同意後才執行**）。**PO 本人逐格確認**轉寫與原圖一致，PO 認可才採用目前模型；**PO 不認可 → 升級模型（改 `TRANSCRIBE_MODEL`、提交推送、主對話審查）再抽 10 張**，不設百分比門檻。結果記入 `quickstart.md`「實測」節。依賴 T058、T040。
- [ ] T060 [GATE] [PO] 打開轉寫開關：PO 同意後執行 `python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data --enable-transcription`（只改設定）；之後夜間排程對新圖開始轉寫。回報開關狀態與下一次排程的轉寫結果。依賴 T059 通過。
- [ ] T061 補轉先前累積的圖片：`python3 poc/kb-mcp/investanchors_import.py --data-dir poc/data --retranscribe`（**只讀本機圖片檔，不登入網站**）；驗證：表格內才有的數字或個股代碼可在對話中搜到該文章（SC-008／US3 情境 2）、不一致或無法辨識者有「未轉寫」標示（SC-007）、轉寫失敗的圖可再次補轉。結果回報主對話。依賴 T060。
- [ ] T062 [GATE] [PO] 回補完成後的逐篇核對（SC-001）：回補完成（`completed=1`）後，對真實網站跑 `article_reconcile.py`，與「總覽」中建立時間在半年內的文章逐篇核對，缺漏 0、重複 0。**這是排程安裝後的手動真實網站執行，須依通用規則 8**：當天先確認當晚排程不會再登入（例如當天先停用 `com.alphavibe.investanchorsimport`，核對後再啟用），PO 知情同意；PO 在場、只留手機一台登入；只執行一次。依賴 T057（回補完成）。
- [ ] T063 [GATE] [PO] 上線驗證期（至少兩週，SC-002／SC-005）：每週檢視一次——文章進庫時間 vs 發布時間（驗證 SC-002 的「下一次登入即匯入」、信漏搜只延後觸發）、睡眠補跑是否落在 PO 常用時段（若會與 PO 使用重疊，再加「非 22:30～次日 06:00 不啟動」的時間窗守衛，另開任務）、`import_runs` 的登入次數與 `logged_out`、帳號未被鎖定／停用、`abandoned` 與 `id_time_ok=0` 數量、轉寫開關開啟後的成本與失敗率、通知是否過量。結論回報主對話並更新 `research.md` R8／R12 的「依上線後觀察調整」。依賴 T055。

---

## Dependencies & Execution Order

### Phase 依賴
- **Phase 1（Setup）**：T001 先；T002 可與之平行。
- **Phase 2（Foundational）**：依賴 Phase 1；**阻擋所有 User Story**。內部：T004 → T005 → T006 → T007（同檔順序）；T003、T008、T010 可與 T004 平行；T009 依賴 T007；T011 依賴 T001。
- **Phase 3（US1）**：依賴 Phase 2。T012、T015 可平行；T013 → T014（同檔）；T016 依賴 T007／T009／T012；T017～T019 依序在 `investanchors_import.py`；T020 依賴 T013～T019；T021 依賴 T020；T022 → T023 → T024 為關卡順序（審查 → 真實單篇 → 獨立驗收）。
- **Phase 4（US2）**：依賴 Phase 2（測試用合成資料，不必等 T023）。T025 → T026 → T027／T028（兩 server 不同檔可平行）→ T029／T030 → T031 → T032。
- **Phase 5（US3，程式）**：依賴 US1 的 `import` 流程（T017）。T033、T034 為研究／決策，可與 US2 平行；T035 依賴 T034；T036 依賴 T033；T037 依賴 T035＋T036；**T038 依賴 T004／T006／T037**；T039 依賴 T025／T037；T040 依賴 T037／T038；T041 為關卡。**全程不需金鑰、不需真實圖片。**
- **Phase 6（US4）**：依賴 US1（`import` 模式與清單讀取）。T042 → T043 → T044；T045 可平行；T046 依賴 T042～T045；**T047（審查與獨立驗收）→ T048（真實網站手動試跑）**。
- **Phase 7（上線）**：依賴 US1～US4 全部。T049、T050、T051 可平行；T052 依賴 T049～T051 及所有程式；T053 依賴 T052；T054 依賴 T053；**T055（部署）依賴 T049／T050／T054**；T056 依賴 T055。
- **Phase 8（上線後）**：T057 依賴 T055；T058 依賴 T057；T059 依賴 T058 與 T040；T060 依賴 T059 通過；T061 依賴 T060；T062 依賴 T057（回補完成）；T063 依賴 T055（全程觀察）。

### 順序驗證（上線流程）
US1、US2、US4 與 US3 **程式**都通過審查與獨立驗收（T024／T032／T041／T047）→ 全面驗收與最後審查（T053～T054）→ 部署與安裝排程（T055）→ 回補開始、圖片累積（T057）→ 存金鑰（T058）→ 抽查 10 張（T059）→ 打開轉寫開關（T060）→ 補轉積壓（T061）。

### 可平行的任務
- T002 ‖ T001；T003 ‖ T008 ‖ T010（與 T004～T007 序列平行）。
- T012 ‖ T015（US1）；T027 ‖ T028（US2，不同檔）。
- US2 與 US3 的研究任務（T033／T034）可平行；T035 ‖ T036（不同檔）。
- T045（reconcile）‖ T042～T044。
- T049 ‖ T050 ‖ T051。

### 需要 PO 配合的任務
T023（首次真實執行）、T048（真實手動回補試跑）、T055（部署／安裝排程同意）、T056（手動白名單）、T057（觀察回補與圖片累積）、T058（存 API 金鑰）、T059（抽查 10 張逐格確認）、T060（同意打開轉寫開關）、T062（SC-001 核對，須先處理當日排程）、T063（上線驗證期）。

---

## Implementation Strategy

### MVP 優先（US1）
1. Phase 1 → Phase 2（基礎，含共用 session 抽取，探查測試須保持全綠）。
2. Phase 3 US1：假網站＋假信箱全程可測 → T022 審查 → T023 真實單篇（測試目錄）→ T024 獨立驗收。**此時 US1 即可獨立交付**（新文章自動進庫、無信不登入）。
3. 其後依序 US2（對話可查）、US3 程式（合成圖＋假模型，開關預設關閉）、US4（半年回補）；每個階段結束都：提交推送 → 通知主對話審查 → 獨立驗收 → 才進下一階段。

### 上線與轉寫啟用（分段，轉寫最後才開）
- **部署前**：US1、US2、US4 與 US3 的**程式**全部通過審查與獨立驗收，再做全面驗收與最後審查，才部署（T055）。部署時轉寫開關**維持關閉**：圖片照常下載、標 `untranscribed`、不呼叫模型。
- **部署後**：回補隨排程自動開始（每天最多 5 篇，約 20 天），圖片逐漸累積。累積 ≥10 張且含長圖後，PO 存金鑰（不會啟動轉寫）→ 抽樣 10 張轉寫並逐格確認 → 通過才打開開關 → `--retranscribe` 補轉積壓。不通過則升級模型再抽。
- 這樣 PO 存金鑰與模型準確度驗證之間不會有「夜間排程偷偷開始轉寫」的空窗。

### 風險提醒
- 真實網站的版面可能與探查時不同：scraper 取不到內文就標失敗、不寫殘缺（T014／T018）。
- ID＝建立時間的規律只有 31 筆樣本：防呆（T003／T042）與累計通知必須保留。
- 登出是帳號安全的核心：任何改動 scraper 的任務都要重跑 45 個探查測試（含 SIGTERM 與隱藏選單 DELETE）。
- 每日登入上限記在各自的資料庫：手動真實網站執行與正式排程同日重疊會登入兩次（通用規則 8）。

---

## PO 待辦清單（彙整）

| # | 任務 | 內容 | 時機 |
|---|---|---|---|
| 1 | T023 | 首次真實網站執行（測試目錄 `poc/data-test-articles`）：在場、**電腦瀏覽器登出、只留手機一台**、在對話親自確認 | US1 審查通過後 |
| 2 | T048 | 真實網站手動試跑回補（測試目錄）：同上在場確認 | US4 審查與驗收通過後 |
| 3 | T055 | 同意部署到 AlphaVibe-prod、安裝 launchd 排程並實跑驗證一次（轉寫開關維持關閉） | 上線前最後審查通過後 |
| 4 | T056 | 在 `~/.claude` stock-researcher 白名單手動加入 `search_articles`／`get_article` | 部署後 |
| 5 | T057 | 觀察回補開始與圖片累積（≥10 張且含長圖） | 部署後數日～數週 |
| 6 | T058 | 把視覺模型 API 金鑰存進鑰匙圈（`stnd-investanchors` / `vision-api-key`，`-w` 後不接值，互動輸入；用「存在與否」驗證）；存了不會啟動轉寫 | 圖片累積達標後 |
| 7 | T059 | 同意跑抽查（少量 API 費用）並**逐格確認** 10 張（含長圖）轉寫；不認可則升級模型再抽 10 張 | 存金鑰後 |
| 8 | T060 | 同意打開轉寫開關（`--enable-transcription`） | 抽查通過後 |
| 9 | T062 | 回補完成後的 SC-001 逐篇核對：在場、只留手機一台、**當天先停用夜間排程再執行**（通用規則 8） | 回補完成後 |
| 10 | T063 | 上線驗證期（≥2 週）觀察與回報；必要時調整每週核對頻率（R12）或加時間窗守衛 | 上線後 |
| 11 | T034 | （條件式）若切片實作需新增 Pillow 等依賴，由 PO 決定 | US3 程式階段 |
