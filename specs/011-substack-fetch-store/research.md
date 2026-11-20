# Research: Substack 文章抓取與儲存（011，第 1 包）

**Date**: 2026-11-19 ｜ 格式：每題 Decision / Rationale / Alternatives。
引用既有程式一律「檔案:行號」（2026-11-19 於分支 `011-substack-fetch-store` 讀取）；**本階段未發出任何網路請求**，
凡依賴站方實際行為者標 **[首跑確認]**，設計已寫成對各種結果都成立。標 **[PO 已決定]** 者為 2026-11-20 PO 對 plan.md 15 項待決的回答（見 plan.md「已決定」表與 spec Clarifications Q7～Q13）。

---

## R0. 重用邊界總表（決定「哪些拿來用、哪些不碰、哪些另寫」）

| 既有模組 | 處置 | 依據（檔案:行號） | 理由 |
|---|---|---|---|
| `poc/kb-mcp/article_data_guard.py` | **原樣重用**（import `resolve_data_dir`） | `article_data_guard.py:21-33` | 邏輯與資料庫無關：未指定拒絕、realpath 後指向正式目錄須 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`；錯誤訊息提到 `poc/data-test-articles/` 僅是字面，不影響行為 |
| `poc/kb-mcp/investanchors_redact.py` | **原樣重用**（`safe_error`、`find_leaks`、`assert_clean`） | `investanchors_redact.py:24-35`、`:38-61` | 010 已驗證的遮蔽與負向斷言；011 另加「不得含標題／文章網址」的禁止字串 |
| `poc/kb-mcp/notify.py` | **原樣重用**（`send_telegram`、`telegram_config`） | `notify.py:50-58`、`:61-95` | 不拋例外、回傳 (成功數, 錯誤清單)；011 只看成功數與錯誤**數量**，不記錄錯誤原文（見 R4） |
| `poc/kb-mcp/claude_cli_runner.py` | **原樣重用**（僅手動轉寫試跑：`ClaudeCli`） | `claude_cli_runner.py:412-428`、`:467-490`、`:492-535` | 只走 claude.ai 訂閱、旗標與環境白名單防呆（`:61` 白名單含 USER／LOGNAME）、撞限即停（`:137-157`）；類別本身不碰任何資料庫 |
| `poc/kb-mcp/transcription_pipeline.py` 的 `prepare_workdir` | **只 import 函式**（不執行流水線、不開 `articles.db`） | `transcription_pipeline.py:99-127` | 單圖／長圖切片暫存夾，已在 010 實測；**注意（驗收指出）**：`transcription_pipeline.py:49-56` 在模組頂層 import `article_store`、`article_verification` 等模組，所以 `substack_transcribe` import `prepare_workdir` 會**間接載入 `article_store` 模組，但不開庫**（`run()` 在 `:509` 才開庫）。T-A 靜態測試只能證明 011 自己的原始碼沒有 `articles.db` 字樣，證明不了間接載入的行為，因此須另有執行期證明 T-C（見 R1） |
| `poc/kb-mcp/article_store.py` | **011 不 import、不開啟**；只有健檢以既有 `open_readonly` 讀 `pipeline_run` 耗時 | `article_store.py:27`（`DB_FILENAME="articles.db"`）、`:473-485`（mode=ro）、`:148-151`（`pipeline_run.finished_at`） | FR-006／FR-021：011 的程式路徑在結構上不可能寫 `articles.db` |
| `poc/kb-mcp/article_images.py` | **不重用，比照其安全規則另寫** `substack_images.py` | `article_images.py:26-31`（拒絕跨主機轉址）、`:47-97` | 綁定 `ArticleStore.list_images/set_image_file` 與定錨的 5～15 秒隨機間隔（`investanchors_limits`），125 張圖會跑 20 分鐘以上；安全規則（主機白名單、副檔名白名單、20MB 上限、`.part`＋`os.replace`、固定路徑）照抄 |
| `poc/kb-mcp/investanchors_mailbox.py` | 不用 | — | FR-001：不用 Gmail 通知信 |
| `poc/kb-mcp/investanchors_import.py` | 只參考慣例（依賴注入、`ALERT_TEXTS` 固定文字、`run(argv, **deps)`） | `investanchors_import.py:60-76`、`:106-108`、`:1058-1066` | 流程完全不同（登入／scraper），不共用程式碼 |
| `poc/kb-mcp/backup_databases.py` | **小幅修改**（見 R7） | `:37`、`:45`、`:136-161` | 可選庫機制已存在 |
| `poc/kb-mcp/check_scheduled_jobs.py` | **小幅修改**：新增檢查函式＋登記 `CHECKS`（見 R7） | `:161-178`、`:450-458`、`:461-468` | 010 同一模式 |
| `poc/kb-mcp/rotate_logs.py` | **不改** | `rotate_logs.py:30`（`~/Library/Logs/alphavibe-*`） | 011 日誌命名 `alphavibe-substack*.log` 即自動納入 |
| `ops/deploy.sh` | **不改** | `ops/deploy.sh:50-63`（只在特定檔變動才重建）、`:65-67`（只重啟 reportserver） | 排程每次執行才讀程式；011 無新套件、無前端 |
| `app/article_deps.py` | 不改、不用 | `app/article_deps.py:30-50` | 第 1 包沒有任何 FastAPI／MCP 入口（第 2 包才有） |
| `keychain_secrets.py` | 不用 | — | 公開 RSS 無密碼；手動轉寫也不取鑰匙圈 token（R1） |

---

## R1. Q-122 手動轉寫路徑（FR-022～FR-024、US6）

**Decision（方案 A）**：新增 `poc/kb-mcp/substack_transcribe.py`，**只 import** 010 的兩個低階元件——
`claude_cli_runner.ClaudeCli`（`claude -p`、訂閱專用防呆）與 `transcription_pipeline.prepare_workdir`（暫存夾／長圖切片）——
讀寫對象一律是 `substack.db`（新表 `transcription_trial`、`image_transcription`）。每張圖兩次呼叫：reader-1（預設 sonnet）＋
驗證者（不同別名，預設 opus，`call(..., verify_text=...)`），**不跑 PaddleOCR**（試跑只驗流程；Paddle venv 是 010 的選用依賴）。

**010 不變的證明（自動化測試設計，FR-021／FR-024／FR-031／SC-003／SC-004）**：

| 測試 | 做法 | 守住什麼 |
|---|---|---|
| T-A 結構隔離（靜態） | 讀 `substack_*.py` 原始碼：不得出現 `articles.db`、`ArticleStore(`、`article_store` 的寫入方法名；`transcription_pipeline.py`、`article_store.py`、`investanchors_import.py` 不得出現 `substack` 字樣 | 011 程式碼不碰 010 庫；010 程式碼不認得 011 |
| T-B 流水線不選取 011（執行期） | 暫存資料目錄同時放 010 fixture `articles.db`（含待轉寫圖）＋已下載圖片、含圖位標記的 `substack.db`；呼叫 `ArticleStore.images_to_transcribe()`（`article_store.py:998-1001`）、`images_to_backfill()`（`:1016`）、`pipeline_images_to_verify()`（`:941-959`）、`images_for_manual_export()`（`:991`）、`pipeline_pending_counts()`（`:929-937`）以及 `transcription_pipeline.run(["--data-dir", d, "--dry-run"])`；斷言回傳只含 010 fixture 的 image_id，且 `substack.db` 位元組與 mtime 不變 | FR-021「MUST 有自動化測試證明流水線不會選取 011 文章」 |
| T-C 手動轉寫不動 010（含執行期證明） | 以假 runner 跑完 `substack_transcribe.py`（**含 import 階段**，在全新子行程中執行以涵蓋間接載入），前後比對 `articles.db` 位元組（比照 `tests/test_article_verification.py:868-875` 的 `db_bytes()` 寫法）、資料目錄檔案清單（不得新建 `articles.db`）、`~/Library/LaunchAgents` 不在測試寫入範圍（以注入路徑驗證不寫 plist）。**另加執行期攔截**：整個流程期間攔截 `sqlite3.connect` 與 `builtins.open`／`os.open`，斷言沒有任何開啟路徑的 realpath 以 `articles.db` 結尾（含 `-journal`／`-wal`）；並斷言 `article_store.ArticleStore` 未被實例化（以 monkeypatch 讓 `__init__` 拋例外，流程仍須完成）。這樣「間接載入 `article_store` 模組」是被明確允許且被證明無副作用的 | FR-024、US6-AS2 |
| T-D 不可排程 | 缺少或不符確認碼時拒絕（主防線：確認碼綁定當日 `--plan`，無人值守的排程拿不到）；次防線：環境變數 `XPC_SERVICE_NAME`（launchd 啟動時設為該 job 的 Label）**以 `com.alphavibe.` 開頭**（即本專案任一排程 plist 的 Label）時拒絕。**不用「`XPC_SERVICE_NAME` 是否存在」判斷**（注意：「launchd 啟動時 XPC_SERVICE_NAME 等於 plist Label」為**未實測假設**，上線前須以 launchd 實跑一次確認；此變數會被子行程繼承，由常駐服務 reportserver 開出的行程〔例如管家 Remote Control 的 claude〕也可能帶 `com.alphavibe.` 前綴而被誤拒——此為次防線，主防線是確認碼，誤拒時改由 Mac 終端機手動執行。）：macOS 從 Terminal／VS Code／Claude Code 開出的行程也常帶非空值（例 `application.com.microsoft.VSCode…`），會誤拒 PO 的手動轉寫。測試案例：未設、`0`、`application.com.microsoft.VSCode.1234.5678` → 不因此拒絕；`com.alphavibe.substackimport`、`com.alphavibe.transcriptionpipeline` → 拒絕。另掃描 `ops/launchd/` 沒有任何引用 `substack_transcribe.py` 的 plist | FR-022「MUST NOT 排程」 |
| T-E 既有 010 全套 | `python3 -m unittest discover -s poc/kb-mcp/tests` 前後皆綠（tasks 階段必列） | SC-004 |

**PO 當下確認額度的機制（FR-020、US6-AS4）**：兩段式。
1. `--plan`：零網路、零模型呼叫，列出選中文章（內部 id、作者代號、發布日、圖數，不印標題）、預估 `claude -p` 呼叫次數（圖數×2）
   與 **確認碼**（以選中 image_id 清單＋日期算出的 6 碼雜湊）。
2. PO 在對話中說「確認」後，Claude 才執行 `--run --confirm <確認碼>`；確認碼不符（清單變了）、跨日、或由本專案排程（`XPC_SERVICE_NAME` 以 `com.alphavibe.` 開頭，見 T-D）啟動即拒絕。
確認碼不是密碼，只是「把 PO 看到的那份計畫綁定到這次執行」，避免同一句「確認」被套到別份清單。
**不取鑰匙圈 token**：`ClaudeCli(token_getter=None)`（`claude_cli_runner.py:417-424` 允許），沿用 Mac 本機 claude.ai 登入
（`ops/launchd/com.alphavibe.transcriptionpipeline.plist` 註解已記錄背景環境可直接用訂閱登入）——避開 FR-020 的鑰匙圈確認。
每次真實呼叫前照 010 先跑 `check_flags`／`check_auth`（`:453-490`），非 claude.ai 訂閱一律中止。

**試跑紀錄格式（US6-AS3）**：`transcription_trial` 一列＝一次試跑：`started_at`、`finished_at`、`confirm_code`、`articles`（篇數）、
`images_attempted`、`images_ok`、`images_not_table`、`images_failed`、`claude_calls`（實際呼叫次數＝「消耗」）、`models`、
`result`（`ok`／`partial`／`aborted_usage_limit`／`aborted_login`／`aborted_auth_mode`／`refused`）、`reset_hint`；每張圖結果在
`image_transcription`。stdout 只印上述數字與代碼。**限制**：`claude -p` 不回傳訂閱額度百分比，「消耗」只能記呼叫次數與圖數 **[PO 已決定：B8]**（FR-024）。

**選取規則（FR-023）**：每位啟用作者取「完整度 F、至少 1 張已下載圖」中最新的 `--per-author N` 篇（N=1～3，預設 1）；
也可 `--article-ids` 指定，但每篇須通過同一規則、每作者 1～3 篇。某作者沒有符合文章 → `--plan` 明列「該作者無符合條件文章」，
**不自動放寬**，由 PO 決定是否仍執行。

**已知限制 [PO 已決定：B7，FR-022]**：010 的轉寫提示詞是「表格圖轉寫員」（`claude_cli_runner.py:80`），非表格圖（折線圖、照片）會被判 `is_table=false`、
只記「非表格」不產生文字。改提示詞＝改 010 程式，違反「重用、不改 010」；建議試跑接受此限制，日後要轉寫非表格圖再另議。

**Alternatives considered**：
- B. 把 011 文章轉成一份臨時 `articles.db`，直接跑 010 `transcription_pipeline.py` 再搬回結果——需偽造 010 schema、`pipeline_enabled`、
  每日上限計數，且一旦資料目錄指錯就可能寫進正式 `articles.db`；拒絕。
- C. 給 `ArticleStore`／流水線加「來源」參數，讓它也讀 `substack.db`——直接改 010 行為與測試，違反 FR-024／FR-031；拒絕。
- D. 沿用 010「方案 D」互動式匯出／匯入（`article_manual_transcribe.py`）——它綁定 `ArticleStore` 與 `articles.db` 的 image_id，
  要改才能指向 011；拒絕。

---

## R2. Mac 睡眠錯過 22:00 的補跑（spec Assumptions、Edge Cases）

**Decision**：沿用 launchd `StartCalendarInterval` 的既有慣例（010 全部排程皆如此）＋一個固定補跑時段＋程式內「排程日」判斷：
- plist 兩個時段：**22:00（主）**與 **01:00（補跑）**，兩者都帶 `--scheduled`。01:00 不在禁用時段清單內（12:30、20:15、23:00、23:15、23:40、02:00、
  03:30、03:45、04:00、06:00、07:45、09:30、17:00）。
- 「排程日」＝當日 22:00 起至次日 21:59（`schedule_day` ＝ 啟動時刻減 22 小時後的日期）。帶 `--scheduled` 的執行若發現**本排程日已有一筆實際執行過的排程執行開始過**（不論成敗）→ 零網路結束，只記一行
  （因此 22:00 正常跑過時，01:00 不會再打站方，也不違反 FR-005「不連續重試」）。
  **判斷必須排除 `run.result` 為 `deferred`／`already_done` 的列**（它們只是「沒執行」的紀錄，不能讓補跑誤以為當日已跑）；只看 `trigger IN ('schedule','catchup')` 且 `result NOT IN ('deferred','already_done')` 的列。
  **假時鐘邊界測試（tasks 必列）**：21:59（屬前一排程日；前一日未跑則補跑、已跑則 `already_done`）、22:00（新排程日，執行）、23:59 與 00:59（`deferred`）、01:00（當日未跑則執行、已跑則 `already_done`）、23:00（`deferred` 起點）、以及「22:00 執行 → 23:30 醒來 `deferred`／`already_done` 不影響後續 01:00 判斷」的序列。21:59 補跑後 22:00 又起算新排程日的情形，由每作者最小間隔（FR-004）擋住重複請求，屬可接受的已知交疊。
- launchd 睡眠語意（本機 `man launchd.plist` 實讀）：「Unlike cron which skips job invocations when the computer is asleep, launchd will start the
  job the next time the computer wakes up. If multiple intervals transpire before the computer is woken, those events will be coalesced into one
  event」。所以 Mac 一醒來就可能在任意時間啟動一次。
- **與 23:00／23:40 錯開**：帶 `--scheduled` 且啟動時刻落在 **23:00～00:59** → 不執行、零網路，記「延後至 01:00 補跑」；01:00 時段接手。
  醒來時刻在其他時間（例如整夜睡眠、07:00 才醒）→ 立即補跑一次（RSS 不受 05:00～18:00 時窗限制，FR-018）。
- 程式另有**單次執行牆鐘預算**（`RUN_BUDGET_SEC=1200`，20 分鐘，以 `time.monotonic()` 計，**強制中止而非只停止開新圖**，驗收指出的鎖占用風險）：
  (1) 圖片下載階段的期限＝預算減 120 秒（18 分鐘），為通知與摘要保留 2 分鐘；每次網路操作的逾時一律取 `min(原逾時, 剩餘時間)`，期限到時進行中的下載被中斷、`.part` 刪除、該圖狀態與 `fail_count` 不變；
  (2) 20 分鐘整體期限到時：停止一切作業，未發出的通知維持 `pending`（下次補發），寫完 `run`（`result='aborted_budget'`、`budget_exhausted=1`）、**釋放鎖**、exit 1；已提交的文章各自完整（逐篇交易），不留半寫入；
  (3) 單篇文章的交易寫入不可中途被預算打斷（寫入毫秒級，期限檢查只在交易之間）。
  這樣鎖最長持有約 20 分鐘，不會因網路卡住而長時間占用、擋住第 2 包的即時取得與手動操作；22:00 啟動的執行最晚約 22:20 結束，遠早於 23:00。實際時長記在 `run` 表，健檢回報（Q-105 以日誌實證）。
  測試：假時鐘＋會卡住的假 HTTP，斷言在預算內中止、鎖已釋放、無 `.part` 殘留、未通知者仍為 `pending`。

**Rationale**：010 的 `check_investanchors_import` 已把「Mac 睡眠導致間隔不足」當成既知情境（`check_scheduled_jobs.py:347-353`），
launchd 醒來補跑是全專案慣例；011 只寫自己的庫與鎖，即使與 010 同時跑在資料層也不衝突（R8），錯開時窗是為了讓 23:00 登入類排程
與 23:40 流水線的日誌與網路單純，不是正確性需求。

**Alternatives**：只靠 launchd 醒來補跑、不設 01:00（醒來落在 23:00～00:59 會整天漏跑）；`StartInterval` 每小時輪詢自判（官方明言睡眠時會漏、
且每小時喚醒）；`RunAtLoad`（開機即打站方，與 010 「安裝不得立即執行」慣例相反）。**[PO 已決定：A2]** 22:00 主排程、01:00 補跑、23:00～00:59 醒來延後交 01:00、同一排程日只實際執行一次（FR-017）。

---

## R3. token 排程耗時紀錄（FR-030、SC-010）

**Decision**：在 `check_scheduled_jobs.py` 新增 `check_token_schedule_gaps(data_dir, agents_dir=~/Library/LaunchAgents)`：
- **登記表**（同檔常數 `TOKEN_JOBS`）列出「會消耗 AI agent token 的排程」與其耗時來源。2026-11-19 盤點只有一個：
  `com.alphavibe.transcriptionpipeline`（23:40，`claude -p`），耗時來源＝`articles.db` 的 `pipeline_run`（`started_at`／`finished_at`，
  `article_store.py:148-151`、`:896-911`），以既有 `ArticleStore.open_readonly`（`:473-485`）唯讀讀取。011 排程不耗 token，不列入；
  手動轉寫不排程，不列入。（`grep -l claude ~/Library/LaunchAgents/com.alphavibe.*.plist` 只命中 transcriptionpipeline 與常駐的 reportserver；
  reportserver 不是排程。）
- **排程時刻**：以標準庫 `plistlib` 讀已安裝的 plist 的 `StartCalendarInterval`；未安裝 → 「未安裝，不納入」。
- **預估耗時**＝最近 10 筆已完成（`finished_at` 非空）執行的**最大**耗時（保守）；0 筆 → 該排程的判斷只輸出「無耗時紀錄、無法判斷」，**不猜**。
- **判斷**：把所有 token 排程的每日觸發時刻放在 24 小時環上排序，對每一對相鄰觸發（A→B）若 `間隔 < 預估耗時(A) + 30 分鐘` →
  `warning`「提醒：A 與 B 間隔 X 分，小於 A 的預估耗時 Y 分＋30 分緩衝，請考慮調整排程（系統不會自動修改）」。只有一個時段的排程，其與自身的間隔是 24 小時。
- 新增 token 排程時，維護者須把它加入 `TOKEN_JOBS`（並指定耗時來源，否則只會回報無法判斷）——寫進 quickstart 接手備忘。

**Rationale**：010 已有可信的耗時紀錄，不需要新寫入；健檢 04:00 跑、有變化才通知（`check_scheduled_jobs.py:489-505`），符合「提醒、不自動改」。
**Alternatives**：解析日誌時間戳（日誌會輪替、格式不保證）；在 011 寫一份自己的耗時表（重複且 011 本身不耗 token）；用平均值（低估尖峰）。

---

## R4. 通知節流與補發（FR-025、FR-032、Edge Cases）

**Decision**：
- 通道：直接呼叫 `notify.send_telegram(text)`（`notify.py:61-95`），比照 `investanchors_import.py:106-108`。
- **節流**：每則之間固定間隔 **1.5 秒**（Telegram 對單一私人聊天約每秒 1 則的上限是一般已知數值，本階段未上網查證；1.5 秒留餘裕）。
  首次約 25 則＋1 則摘要 ≈ 40 秒。
- 每篇文章一則（**含追補存入的文章**，PO 決定 B3，FR-025），依發布時間由舊到新；內容＝作者（出版名稱）＋標題＋完整度，**不含文章連結**（PO 決定 A1，FR-027 例外）；成功＝`send_telegram` 回傳的錯誤清單為空。
- **失敗與補發**：失敗只把該篇 `notify_status` 設為 `failed`、`notify_attempts+1`，**同次不重試**；之後每次執行（排程或手動）先補發
  `pending/failed` 再發新文章；累計 3 次失敗 → `abandoned`，健檢回報張數。文章存檔不受影響（先寫庫、後通知）。
- **錯誤不落地**：`send_telegram` 的錯誤字串可能含例外原文（`notify.py:93-94`）；Bot token 形如 `數字:35字元`，冒號會切斷
  `investanchors_redact._LONG_TOKEN_RE`（`investanchors_redact.py:17`，需連續 40 字元）而**遮不到**。011 一律只記「失敗 N 則」與 HTTP 狀態碼，
  不記錯誤原文。
- **告警策略**（FR-032）：設定檔 `alert_policy`＝`every_failure`（預設、初期）或 `consecutive_3`；403／429 與「回應不是 feed 的 HTML 挑戰頁」
  一律立即告警（後者比照 intake `integration-note.md §2`「視同被擋」**[PO 已決定：B2，FR-005／FR-032]**）。作者級連續失敗次數存 `author.consecutive_failures`，
  200／304 歸零；因最小間隔跳過不增不減。
- **摘要通知**：本次有新文章、有告警或有「feed 20 篇皆為新文」提示時，最後再發 1 則摘要，含新增篇數（P/F/N）、缺圖／放棄張數與**空間現況**
  （FR-025／FR-028；Edge Case「在回報中提示可能漏文」）。沒有新文章且無告警 → 不發任何通知（US1-AS4）。**[PO 已決定：B4]**
- **告警附空間現況**（FR-028「有事件的通知附帶空間現況」）：四種告警文字末尾都附一行「空間：剩餘 X GB；substack.db Y MB；圖片 Z MB」（現況數字，無判定字眼）；逐篇新文章通知不附（其空間現況由同次摘要提供）。空間數字以 `shutil.disk_usage(data_dir)` 與實際檔案大小計算，計算失敗時該行寫「空間：無法取得」而不是省略或猜測。

**Alternatives**：遇 429 依 `retry_after` 等待重送（`notify.py` 不回傳該值，要改 010 共用模組）；合併成單則（違反 Q5／FR-025）；
同次立即重試（可能放大限速）。

---

## R5. 追蹤清單、告警策略、最小間隔的設定檔；追補指令（FR-002、FR-004、FR-008、FR-032、US5）

**Decision**：
- 位置：`<data_dir>/substack_config.json`（正式＝`poc/data/substack_config.json`，`poc/data/` 已在 `.gitignore:10`；`AlphaVibe-prod/poc/data`
  是指向它的 symlink，所以開發資料夾改了、正式排程下次就讀到，**不需部署**）。不放 repo：正式 worktree 不得有手改檔
  （`ops/deploy.sh:28-32` 會中止部署）。
- 格式：JSON（標準庫可讀寫、Claude 易改），完整欄位與驗證規則見 `contracts/config-format.md`。
- **只透過 CLI 修改**：`substack_config.py`（`init`／`show`／`validate`／`add`／`enable`／`disable`／`set-interval`／`set-alert-policy`）——
  驗證通過才寫，寫入用暫存檔＋`os.replace`（原子），每次寫前把舊檔複製為 `substack_config.json.bak-<時間>`（保留 10 份）；
  寫正式目錄同樣要 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`（`article_data_guard.py:29-32`）。PO 在對話中提出，Claude 執行 CLI 並把 `show` 結果回報。
- **執行期再驗證**：排程讀設定檔時再跑同一份驗證；不合格 → 整次不發任何請求、固定文字告警、exit 2（不猜、不用隱性預設值，FR-012 精神）。
- 首次／重新啟用的 14 天窗：`author.activated_at` 在「該作者第一次以啟用狀態被非 dry-run 執行看到」時寫入（即使該次抓取失敗，重跑沿用同一基準日）；
  上次看到是停用、這次是啟用 → 重新寫 `activated_at`。窗口起點＝`activated_at` 的台北日期往前 14 天 00:00。
- **追補**：`substack_import.py --backfill <作者代號>`（手動）：取鎖、守最小間隔（間隔內拒絕並回報還要等幾分鐘）、條件請求**不帶 ETag**
  （要拿到完整 20 篇）、忽略 14 天窗、去重後存入未存過的條目（`source='backfill'`）；回報 feed 條目數、已存、新存、feed 中最舊一篇的日期，
  並固定提示「早於該日的文章 feed 已不提供，無法取得」（FR-008、US5-AS5、Edge Case）。追補文章逐篇通知（FR-008、FR-025；**[PO 已決定：B3]**）。

**Alternatives**：放 `articles.db`／`substack.db` 的 setting 表（Claude 需寫 SQL，易出錯、不好讀）；放 repo（要 commit＋部署）；
YAML（非標準庫）；讓 Claude 直接手改 JSON（無驗證、無備份）。

---

## R6. 資料庫、圖片、HTML→文字、Read more 偵測、去重、ETag、robots、User-Agent

| 題目 | Decision | Rationale／Alternatives |
|---|---|---|
| 資料庫 | `<data_dir>/substack.db`（SQLite，`check_same_thread=False`，預設 rollback journal、`busy_timeout=5000`、`isolation_level=None` 並一律顯式交易，見 R8）；類別 `SubstackStore`（`substack_store.py`）建構子只建表、**不寫任何資料列**（CLAUDE.md 2026-08-22 教訓）；`open_readonly` 用 `mode=ro` 且庫不存在丟 `FileNotFoundError`、不建檔（比照 `article_store.py:473-485`） | intake 已定名 `substack.db`；不用 WAL：`mode=ro` 讀者在 WAL 下需寫 `-shm`，健檢唯讀開庫會變複雜 |
| 圖片目錄 | `<data_dir>/substack_images/<article_id>/<seq>.<ext>`；路徑不含任何來自網址的片段；寫 `.part` 後 `os.replace`（比照 `article_images.py:92-95`） | 與 `articles_images/` 平行、名稱可辨識 |
| 圖片下載 | `substack_images.py`：https 限定；主機白名單（預設 `substackcdn.com`、`substack-post-media.s3.amazonaws.com`、作者 feed 主機，可在設定檔擴充）；轉址只允許落在白名單主機；`Content-Type` 必須 `image/*`；單檔 20MB；張與張間隔 1 秒；逾時 30 秒；失敗（含白名單外）`fail_count+1`，達 3 → `abandoned` | 白名單外的圖不發請求、記 `host_not_allowed`，3 次後放棄；**[PO 已決定：B5，FR-034]** 白名單初始＝上列兩個固定主機＋各作者 feed 主機，PO 可在對話中以 `add-image-host`／`remove-image-host` 增修；拒絕「任意主機」以防 feed 內容誘導抓內網位址 |
| 封面圖 | `enclosure` 為 `image/*` 且不在內文中 → 以 `seq=0`「封面」下載；`audio/*`／`video/*` 只記型別、不下載 | Q-114 未決；封面是文章圖片的一部分、成本低 |
| HTML→純文字 | `html.parser` 自寫轉換器（`substack_html.py`）：區塊元素換行、`li`→「• 」、`script/style` 丟棄、`iframe/audio/video` 與播放器 div→〔嵌入內容〕／〔播放器〕；`<img>`→`〔圖 N｜圖說：…｜alt：…〕`（`figure` 內的 `figcaption` 併入標記、不重複輸出）；保留原始 HTML 於 `content_html` | 標準庫；保留原 HTML 讓 PO 要求「重新判斷」（FR-033，本包提供，見 R11）時不必重抓 |
| Read more（P） | 去掉尾端空白後，以 `html.parser` 取**最後一個頂層區塊**：是 `<p>`、唯一有意義子節點為 `<a>`、連結文字正規化後等於 `Read more`（不分大小寫）、`href` 為 `https://<host>/p/<slug>` → P（`classify_reason='read_more_tail'`） | 依 `docs/spec-intake/substack-import/raw/2026-11-19-paid-preview-analysis.md` 第 4 行的固定結構；**不看長度**（FR-012） |
| F／N／不確定 | 無上述尾端時：可見文字（扣除圖位與播放器標記、空白）≥ **200 字** → F；< 200 字 → N。下列一律存 P 並標 `uncertain:*`：`content:encoded` 缺漏或空、HTML 無法解析、尾端有 `Read more` 文字但結構或 `href` 主機與文章連結不符、最後區塊含 `Read more` 但後面還有內容 | 實測 N 類 0～38 字、F 類 7.5k～15k 字，200 落在大間隙中；「足夠純文字」門檻＝可見文字 ≥200 字，為明示常數、寫進契約 **[PO 已決定：B1，FR-010]** |
| 去重鍵 | `guid`（文字原樣）與 `link_norm`（https、小寫主機、去 query／fragment、去尾斜線）各有 UNIQUE 索引；任一相同即重複、不覆寫（FR-007）；guid 中 A、link 中 B 的衝突 → 視為重複並計數 `dedupe_conflict` | RSS guid `isPermaLink=false`；兩種網址只存一份（Edge Case） |
| ETag | `author.etag` 存上次回應的 ETag 原字串（含 `W/` 弱標記），下次 `If-None-Match`；304＝無變化、不解析、不寫文章，但仍算一次請求（更新 `last_request_at`） | 實測有 ETag、無 Last-Modified（`integration-note.md §1`） |
| feed 請求 | 每作者每次執行最多 1 次；逾時 30 秒；回應上限 5MB；XML 先拒絕含 `<!DOCTYPE`／`<!ENTITY` 的內容再用 `xml.etree.ElementTree` 解析；作者之間間隔 5 秒；轉址只允許到該作者設定的 feed 主機或 `<x>.substack.com` | 實測 feed 約 0.8～1MB；預先拒絕 DTD 防實體展開 |
| robots.txt | `urllib.robotparser` 判斷 feed 路徑；結果快取在 `robots_cache`（每主機 24 小時，對應實測 `max-age=86400`）；取 robots 失敗時用 7 天內快取，否則該作者本次略過（`robots_unavailable`，算一次失敗）；被禁止 → `robots_disallow`（算失敗，依告警策略） | robots 請求不是 feed 請求，不違反 FR-003 的「至多一次 feed 請求」 |
| User-Agent | `Mozilla/5.0 (compatible; personal-feed-reader/1.0)`（研究實測時用的同款，`raw/2026-11-19-rss-tos-research.md` 第 4 行），不含 email、姓名、網址 | FR-003 通用識別 |
| 發布日缺漏 | `pubDate` 解析不了 → 不能套 14 天窗 → 不存、計數 `no_pubdate`、摘要回報（只有追補會存這類條目） | 不猜日期 |
| 日誌內容 | 只記作者代號、HTTP 狀態、結果代碼、計數、內部 article_id／image_id；**不記標題、文章網址**（Substack slug 常是標題轉寫，等同洩漏）、圖片網址 | FR-026 |

---

## R7. 備份、健檢、日誌輪替、外洩掃描的整合點（FR-026、FR-028、FR-029、US7）

| 整合點 | 改動（檔案：函式／常數） | 對 010 既有測試的影響 |
|---|---|---|
| 備份：資料庫 | `backup_databases.py`：`OPTIONAL_DATABASES = ("articles.db", "substack.db")`（`:45`） | `tests/test_backup_databases.py:90-97` 的前綴不撞（`substack` 不是任何既有前綴的延伸）、`articles.db` 仍在 OPTIONAL；`:112-124` 只在測試建立的庫上斷言，`substack.db` 不存在即略過 → 不受影響 |
| 備份：圖片 | `backup_databases.py` 新增 `OPTIONAL_DIR_MIRRORS = (("substack_images", "substack_images"),)` 與 `mirror_dir(src, dest)`：只複製「目的端不存在或大小不同」的檔案到 `~/AlphaVibe-backups/mirror/substack_images/`，不刪目的端檔案，完成後寫 `.last_sync`；來源目錄不存在 → 略過一行、不建目錄；`main()` 在資料庫迴圈後呼叫 | 新增程式只在來源目錄存在時動作，既有測試的暫存目錄沒有 `substack_images/` → 行為不變。圖片下載後不再變動（無保留期限），鏡像一份即可，不做每日 tar。**已知限制（驗收指出，須如實告知 PO）**：(1) 鏡像**不刪除目的端檔案**——來源端若有圖被移除，目的端仍留；(2) 圖片在來源與鏡像各存一份，**占用翻倍**（備份目的地在同一台 Mac，若與資料目錄同一顆磁碟，等於同一顆磁碟存兩份）；(3) **無完整性驗證**——只比對「檔案是否存在、大小是否相同」，不比雜湊、不能偵測位元腐壞或大小相同的內容差異；`.last_sync` 只代表「同步程序跑完」。**空間限制與首跑確認**：資料所在磁碟是 `/System/Volumes/Data`（可寫的資料卷）；驗收以 `df -h /` 看到的 36%～38% 是唯讀系統卷，**不代表資料磁碟**；本計畫撰寫時的同日實測 `df -h /System/Volumes/Data` 為可用約 20Gi、已用 91%（先前文件寫的「22Gi、90%」是較早數字，以當下實測為準）。因此**首跑時 PO 在場，由 `shutil.disk_usage(<data_dir>)` 與 `df -h <data_dir>` 實際確認資料磁碟剩餘空間**（quickstart 首跑檢核表新增此項），並以首跑的圖片總大小估算鏡像後的翻倍占用；本包不設空間閾值（FR-016、FR-028），只報現況，由 PO 判斷 |
| 健檢：011 狀態 | `check_scheduled_jobs.py` 新增 `check_substack_import(data_dir)`：唯讀開 `substack.db`；不存在＝「尚未建立」ok、不建庫。輸出見 `contracts/health-output.md` | 新函式；登記到 `CHECKS`（`:450-458`）。既有測試以 `assertIn` 檢查名稱（`tests/test_check_scheduled_jobs.py:568-570`），不檢查總數 |
| 健檢：011 備份 | 新增 `check_substack_backup(data_dir, backup_dir)`：比照 `check_articles_backup`（`:161-178`），另檢查鏡像 `.last_sync` | 同上 |
| 健檢：token 間隔 | 新增 `check_token_schedule_gaps(data_dir, agents_dir)`（R3）；**只會回 ok／warning、從不回 critical** | `ExitCodeTest`（`tests/test_check_scheduled_jobs.py:166-175`）只依 critical 判 rc，不受影響；`agents_dir` 可注入，測試不讀真實 LaunchAgents |
| 健檢通知 | **不改** `should_notify`（實際位於 `poc/kb-mcp/check_scheduled_jobs.py:489`，2026-11-20 實讀確認；只在「狀態有變化」時回 True）與 `format_health_message`（位於 `notify.py:98`，只列非 ok 項、`ok` 項略過）——**`notify.py` 只有 `format_health_message`，沒有 `should_notify`**（先前草稿把兩者都歸給 notify.py，已更正）。空間等現況（每日，FR-028）放 ok 項（進狀態檔與 stdout，**不會**因 `should_notify` 而每天發通知），全文占比與 token 間隔提醒放 warning（狀態改變時才通知） | 無 |
| 日誌輪替 | 不改；plist 的日誌檔名 `~/Library/Logs/alphavibe-substack.log`／`.err.log` 自動符合 `rotate_logs.py:30` 的 glob | 無 |
| 外洩掃描 | 新測試 `tests/test_substack_no_leak.py`：比照 `tests/test_investanchors_no_leak.py:70-85` 的四個面（程式輸出、通知、資料庫非資料通道欄位、資料目錄檔名），以 `investanchors_redact.assert_clean` 加禁止字串：測試 feed 的標題標記、內文標記、文章網址 slug；通知允許含標題但不得含內文標記 | 只新增，不改 010 的 no-leak 測試 |

**全文占比提醒（FR-013）的計算**：以文章的「抓取日（台北）」分日，只計 `source` 為 `schedule`／`manual` 的文章（追補不計，避免一次灌入扭曲）。
「近期占比」＝最近一個有新文章的抓取日的 F 數／當日文章數；「近 7 天平均」＝該日之前 7 個日曆日中**有文章的日子**各自占比的平均。
有文章的比較日 < 7 → 只報「目前占比 X%、可比較天數 N」，不下提醒（spec Assumptions）。差距 > 30 個百分點 → warning 提醒。
**風險 [PO 暫解讀，待確認：Q11]**：PO 對 FR-013 的回答是「內文」（語意不明），暫解讀為**維持上述現行算法（近 7 天平均 ±30 個百分點）**，未採用「7 天對 7 天且至少 5 篇才判斷」。兩位作者每天約 0～3 篇，單日占比只能是 0%／33%／50%／100% 這類跳動值，照字面計算可能常誤提醒（只提醒、不處置，不影響匯入）；若 PO 日後否決此解讀，改算法只動 `check_substack_import` 的一個函式，不影響其他設計。提醒措辭用現況（「提醒：全文占比 X%，近 7 天平均 Y%，相差 Z 個百分點」），不用「異常」二字，與 SC-010 並存（PO 決定 #15）。
**重判與占比**：FR-013 計算一律用文章的**原判斷**（`article.completeness`，反映匯入規則當時的輸出），不用重判後的有效值，避免 PO 重判後歷史占比被改寫而掩蓋「站方改版造成整批分類改變」的訊號。

---

## R8. 執行鎖、寫入原子性、與 23:00／23:40 互不搶庫（FR-009、FR-017）

**Decision**：
- 鎖：`<data_dir>/.substack_import.lock`，`fcntl.flock(LOCK_EX | LOCK_NB)`，比照 `transcription_pipeline.py:605-610`；拿不到 → stdout 一行「忙碌」、
  exit 3、**不開庫寫入**（後到者不寫庫，FR-017）。鎖涵蓋整次執行（讀設定→抓取→寫庫→下載圖→通知），由時間預算（R2）限制持有時間。
  手動轉寫、追補、補圖與排程共用同一把鎖。第 2 包的即時取得也會用這把鎖（拿不到回報忙碌）。
- 原子性：**每篇文章一個交易**：`BEGIN IMMEDIATE` → 插入文章列與其全部圖片列（`pending`）→ `COMMIT`；任何例外 `ROLLBACK`，該篇下次再試。
  **Python 3.9 的 sqlite3 陷阱（驗收指出）**：`sqlite3.connect()` 預設 `isolation_level=''`，模組會在 DML（INSERT／UPDATE／DELETE）前**自動**送出隱性 `BEGIN`，且在 DDL 前先 COMMIT 既有交易——與手寫的 `BEGIN IMMEDIATE` 混用會出現「cannot start a transaction within a transaction」或交易邊界不是自己以為的位置，使「單篇一交易」的原子性無聲失效。**決定**：`SubstackStore` 連線一律 `isolation_level=None`（autocommit 模式），所有寫入路徑統一經單一輔助函式 `with store.transaction():`（顯式 `BEGIN IMMEDIATE`、成功 `COMMIT`、例外 `ROLLBACK` 後重拋），**不得**在交易外直接執行任何 DML。建表 DDL 也在自己的顯式交易內完成。
  **回滾測試（tasks 必列）**：(1) 在寫入文章列之後、寫入圖片列之前注入例外 → 斷言 `article` 與 `article_image` 兩表皆無該篇（沒有半寫入）；(2) 在 `COMMIT` 前注入例外 → 同上；(3) 磁碟滿（假 `OperationalError('database or disk is full')`）→ 回滾且 `run.result='aborted_disk'`；(4) 靜態守門：`substack_store.py` 以外的模組不得出現 `.execute(` 於 INSERT／UPDATE 且不在 `transaction()` 內（以 `connect` 後的連線 `in_transaction` 屬性在每個寫入點前後斷言為 False／True）；(5) 排程日判斷與時間預算的假時鐘邊界測試見 R2。
  圖片：檔案先寫 `.part`、`os.replace` 成正式檔名，**之後**才在單一 UPDATE 把狀態改為 `downloaded`（含 sha256、位元組）——資料庫說「已下載」時檔案必然存在；
  若在 replace 與 UPDATE 之間中斷，下次以同一固定路徑覆寫，不留孤兒紀錄。
- 磁碟滿：SQLite `database or disk is full` 或檔案 `ENOSPC` → 當次立即中止（`run.result='aborted_disk'`）、刪 `.part`、固定文字告警、exit 4；
  已提交的文章保留（每篇各自完整），無半寫入（US4-AS4）。此類失敗不計入圖片 `fail_count`（環境問題）。
- **互不搶庫論證**：010 定錨匯入（23:00）只寫 `articles.db`（無 flock），流水線（23:40）只寫 `articles.db` 並持 `.transcription_pipeline.lock`
  （`transcription_pipeline.py:66`）。011 排程只開 `substack.db` 與自己的 `.substack_import.lock`，**從不開啟 `articles.db`**（R1 T-A 靜態測試＋
  執行期以 mock 攔截 `sqlite3.connect` 路徑斷言）。SQLite 鎖是「每個資料庫檔」層級，不同檔案不互相阻擋；flock 也是不同檔案。
  時間上 22:00 執行有 20 分鐘預算、23:00～00:59 啟動會延後（R2）。唯一共用資源是網路與 CPU，量級（2 個 feed 請求＋數十張圖）可忽略。
  健檢在 04:00 以唯讀方式開 `articles.db` 讀耗時（既有慣例，`check_scheduled_jobs.py:312-388` 已如此）。

**Alternatives**：整批一個交易（一篇壞掉全部回滾、且長交易阻擋讀者）；SQLite 自身鎖當執行鎖（無法表達「整次執行」且無法回報忙碌）；
與 010 共用 `.transcription_pipeline.lock`（把不相干的流程互相卡住，且違反 Q-010「011 另設自己的 flock」）。

---

## R9. launchd plist、部署、回滾（FR-017、FR-020、FR-029）

**Decision**：
- 新檔 `ops/launchd/com.alphavibe.substackimport.plist`：`/usr/bin/python3 /Users/stander/My_project/AlphaVibe-prod/poc/kb-mcp/substack_import.py
  --data-dir /Users/stander/My_project/AlphaVibe-prod/poc/data --scheduled`；`WorkingDirectory` AlphaVibe-prod；`EnvironmentVariables` 只放
  `PATH`（`/usr/bin:/bin:/usr/sbin:/sbin`，不需要 node／claude）與 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`（`AlphaVibe-prod/poc/data` 是 symlink，
  guard 以 realpath 判斷，比照 `com.alphavibe.transcriptionpipeline.plist`）；`StartCalendarInterval` 兩筆（22:00、01:00）；
  **不設** `RunAtLoad`／`KeepAlive`；日誌 `~/Library/Logs/alphavibe-substack.log`／`alphavibe-substack.err.log`。
- 安裝（FR-020：須 PO 當下對話親自確認）：`cp` 到 `~/Library/LaunchAgents/` → `launchctl bootstrap gui/$(id -u) <plist>`；新安裝不是重啟常駐服務，
  不涉及 CLAUDE.md 2026-10-29 的 kickstart 教訓；**改 plist 時**才需 `bootout` 後確認舊行程結束再 `bootstrap`。
- 部署：`ops/deploy.sh` **不需修改**（R0）。流程＝合併 PR → 照 CLAUDE.md 的部署指令 → PO 確認後安裝 plist → 先手動 `--dry-run`、再手動跑一次首次匯入（PO 在場看約 25 則通知）→ 隔天看 22:00 日誌。
- 回滾（三層，獨立）：(1) 停排程：`launchctl bootout gui/$(id -u)/com.alphavibe.substackimport`；(2) 程式：`ops/deploy.sh <舊 commit>`；
  (3) 資料：`substack.db`／`substack_images/`／`substack_config.json` 是獨立檔案，刪除或以 `~/AlphaVibe-backups/daily/substack-*.db.gz` 還原；
  因不動 `articles.db`，回滾不需任何 010 遷移（`data-model-note.md §1`）。

**Alternatives**：把 011 掛進既有 plist（混淆責任、改 010 檔）；cron（睡眠時直接跳過）。

---

## R10. 風險與已知坑（CLAUDE.md 教訓紀錄對照）

| 坑 | 對 011 的處置 |
|---|---|
| Python bytecode 快取在 `~/Library/Caches/com.apple.python/…`（2026-09-03） | quickstart 列出：改了程式但行為沒變 → 先 `python3 -c "import substack_import as m; print(m.__cached__)"`；獨立驗收用 `git archive` 乾淨副本 |
| macOS `/var`→`/private/var`（2026-11-16，已踩兩次） | 所有路徑比較（資料目錄、圖片路徑在根目錄下的檢查、鎖檔）一律 `os.path.realpath`；測試用 `tempfile` 目錄必經 realpath |
| 子行程環境須含 USER／LOGNAME（2026-11-16、`claude_cli_runner.py:61`） | 排程本身不開子行程；手動轉寫直接用 `ClaudeCli` 的既有白名單，不另造環境 |
| 巢狀 Claude Code 會帶 `CLAUDE_CODE_*`（2026-09-25） | 手動轉寫在 Claude Code 對話中執行；`ClaudeCli.build_env` 本來就以白名單建環境，不繼承 `CLAUDE_CODE_*`；quickstart 註明 |
| 建構子有副作用（2026-08-22） | `SubstackStore.__init__` 只建表；設定檔 `init` 是明確子命令 |
| 測試寫進正式庫（2026-08-22） | 一律 `--data-dir` 指向 `tempfile`／`poc/data-test-substack/`；guard 先於任何動作 |
| zsh 拆字（2026-10-29） | quickstart 指令不用未加引號的變數清單；腳本以 `bash` 執行 |
| launchd bootout 後立刻 bootstrap 失敗（2026-10-29） | 本功能只新安裝；改 plist 時照教訓先確認舊行程結束 |
| 「規格說應該」≠「已實作」（2026-07-24） | 契約與 quickstart 都標明哪些是本包範圍（無 MCP 工具；重判指令 `--reclassify` **有**，FR-033） |
| 外洩：文章網址 slug＝標題 | 日誌不記文章／圖片網址（R6） |
| 外洩：Telegram Bot token 遮不到 | 不記 notify 錯誤原文（R4） |
| Python 3.9.6 | 不用 `X | Y` 型別、`match`、`str.removeprefix` 以外 3.10+ API；`zoneinfo` 可用（3.9）但沿用 010 的固定 `UTC+8` 常數寫法 |
| feed 首次實跑才知道的事 [首跑確認] | FOMO 的 feed 網址（設定預設 `https://www.fomosoc.com/feed`；研究實測過 `<名>.substack.com/feed` 與自訂網域 `/feed` 皆可用，但未針對這兩位作者記錄網址）、`Read more` 結構在兩位作者上的實際命中、圖片主機是否全在白名單——quickstart 首跑檢核表逐項確認 |

---

## R11. 重新判斷完整度（A3，FR-033；PO 2026-11-20 決定本包提供）

**Decision**：
- **保存原始內容**：`article.content_html`（原樣）已在 data-model；重判只讀它，**不重新請求站方**、不呼叫模型、不發通知。
- **原判斷不覆寫（FR-007 不受影響）**：`article.completeness`／`classify_reason` 永遠是匯入當時的原判斷，沒有任何 UPDATE 路徑；每次重判在新表
  `reclassification`（見 data-model §1.9）**新增一列**，記錄時間、前後類別、依據代碼、判斷規則版本（`substack_html.RULE_VERSION`）、觸發方式。
- **有效完整度**＝該文章最近一筆 `reclassification.new_completeness`，沒有則為 `article.completeness`；以視圖 `article_effective`（唯讀 VIEW）提供，
  查詢與手動轉寫選取（FR-023 的「F 類」）都用有效值；FR-013 占比用原判斷（見 R7）。
- **規則**：重判呼叫與匯入時**同一個**分類函式（`substack_html.classify(content_html, link, ...)`），用「當下程式裡的規則」；所以站方改版後 PO 先調整規則（走程式變更）、再要求重判。
  `body_text` 不重算、不覆寫（重判只改判斷，不改已存內容）。
- **指令**（`contracts/cli.md §1`）：`substack_import.py --data-dir DIR --reclassify (--article-ids IDS | --author KEY) [--dry-run]` 與唯讀
  `--reclassify-history ARTICLE_IDS`。取同一把執行鎖（拿不到＝忙碌 exit 3）；零網路、零模型；輸出只有計數與內部 id
  （檢查篇數、未變、改變 P→F 幾篇…），不含標題。結果相同（新舊類別一樣）也記一列（證明有重判過、規則版本為何）；`--dry-run` 只列「會改變」的 id、不寫庫。
- **PO 對話流程**：PO 說「FOMO 最近的文章判斷怪怪的，幫我重判」→ Claude 先 `--reclassify --author fomosoc --dry-run` 回報會改幾篇 → PO 同意後正式執行 → 回報結果與歷史。
- **測試**：重判前後 `content_html`／`body_text`／`article.completeness` 位元組不變；`reclassification` 新增 N 列；兩次重判後有 2 列、順序正確；重判期間攔截 `urllib`／`subprocess`
  確認零呼叫；有效值＝最近一筆；`--author` 範圍只含該作者；不存在的 id 回報而非靜默略過。

**Alternatives**：直接 UPDATE `article.completeness`（違反 FR-033「不覆寫歷史」與 FR-007）；只存「最新重判值」欄位在 article（丟失歷史）；重判時重新抓 feed（違反「以保存的原始內容」；feed 也只保留 20 篇）。
