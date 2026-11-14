# Research: 定錨產業筆記文章自動匯入

**Date**: 2026-11-15 ｜ 格式：Decision / Rationale / Alternatives。標 **[PROBE]** 者無法在沒有 PO 帳號的情況下
查證，須在 PO 的 Mac 上執行 `article_probe.py`（R0）後回填；設計已寫成對每種結果都成立。

## R0. 需在 PO 的 Mac 探查的事項（spec Assumptions 末條，plan 第一步）

| # | 未知 | 會影響什麼 | 設計對各結果的因應 |
|---|---|---|---|
| P1 | 「總覽」清單是否分頁／無限捲動、總篇數 | 回補批次數、核對方式、清單讀幾頁 | 讀取以「翻頁至沒有新 ID 為止」為通則；若無限捲動，scraper 改以捲動＋ID 去重，仍受單次篇數上限約束 |
| P2 | 登入狀態有效期、**伺服器端登出機制**（按鈕／endpoint） | FR-008 是否做得到；伺服器端 session 是否被釋放 | **伺服器端登出是必要步驟**，`context.close()` 只清本機 cookie、不算數。探查找不到登出機制 → **停止並回報 PO，不進入實作**；找到則以「再訪登入頁得到登入表單」驗證（SC-004） |
| P2a | 新登入是否會把 PO 其他裝置踢下線 | 排程登入是否干擾 PO 手機／電腦使用 | 需 PO 配合觀察一次（探查時請 PO 手機保持登入） |
| P2b | 網站如何計算「上線裝置」：登出後名額是否**立即釋放** | 兩台上限（FR-008）與排程時段安排 | 若不立即釋放（例如以 session 逾時計），每日登入次數與時段須更保守，並回報 PO 重新取捨 |
| P3 | 開啟文章是否改變已讀（細體／粗體） | FR-009 例外是否如預期；是否可用已讀狀態輔助 | 僅確認，不依賴已讀狀態判斷新舊（spec：身分只靠文章 ID） |
| P4 | 通知信連結是否直指 `/user/vip_contents/<ID>`（或是追蹤轉址） | 能否從信直接取得 ID、不開信內連結 | 若為追蹤轉址：**不跟隨轉址**（會替 PO 留下點擊紀錄且可能計入存取），改以信內標題比對清單取得 ID；若直指則直接取 ID |
| P5 | `lv=` 參數意義、清單日期列結構、公告標題格式 | 清單解析、【公告】略過 | 解析器以標題前綴 `【公告】` 判斷，不依賴 `lv` |
| P6 | 文章頁 DOM：內文容器、表格圖與一般圖的區分 | 取全文、判斷哪些圖要轉寫 | 見 R5：不可靠區分時，**所有內文圖都送轉寫**，由模型回報「非表格」 |
| P7 | 是否有同一 IP／行為頻率偵測、登入頁是否有隱藏欄位或 CSRF token | 封鎖偵測規則 | 先用起始值（5 篇／每日 1 次／30–90 秒）並再保守 |

**探查規約（保護帳號，硬性）**：只在 PO 在場、一次性執行；總計登入 1 次、開啟清單 ≤3 頁、開啟文章 ≤2 篇；
全程單一 context，結束即登出；輸出只寫結構事實（DOM 選擇器、頁數、有無分頁）到 `poc/data/articles_probe/`
（gitignore 目錄，**不存全文、不存 cookie**）。工具規格見 contracts/cli.md §2。

## R1. 觸發與去重

**Decision**: 三種觸發：(a) Gmail 有「未處理的定錨新信」；(b) 每週核對日（週日，且上次核對 ≥6 天前）；(c)
回補未完成。全部以 **文章 ID（`/user/vip_contents/<數字>` 的數字）** 為主鍵；信件 Message-ID 只用來記
「這封信已看過」，不是文章身分（009 教訓：同一內容換來源會被當新資料）。
**Rationale**: 滿足 FR-003／FR-006／SC-003：沒有新信且非核對日且回補完成 → 登入次數 0。
**Alternatives**: 只靠清單輪詢（每天登入，違反低頻）；以信件為身分（漏信或多信即重複／漏抓）。

## R2. 取信

**Decision**: 新檔 `investanchors_mailbox.py`，沿用 `statement_mailbox.py` 的骨架：`IMAP4_SSL imap.gmail.com`、
`select(readonly=True)`、`BODY.PEEK[]`（信不會被標已讀）、`X-GM-RAW "from:postmaster@mailer.investanchors.com
newer_than:Nd"`。解析 HTML／text 內文取標題與連結；寄件者與天數參數化，不改 009 的常數。Gmail 位址與
app password **沿用既有鑰匙圈項目** `stnd-statement-import` 的 `gmail-address`／`gmail-app-password`。
**Rationale**: 既有、已上線驗證（009）；唯讀不改信箱狀態。
**Alternatives**: 把 009 的 `fetch_statements` 改成泛用（動到已上線功能且含 PDF 專用邏輯，風險不值得）；Gmail OAuth（需新授權流程）。

## R3. 瀏覽器抓取與登入

**Decision**: 新 `scraper/investanchors_scraper.js`（Node/Playwright）；Python 以 `subprocess.Popen` 傳入 JSON
指令、讀 JSONL 結果，與 `flight_scraper.js` 同介面慣例（`result`／`summary{blocked}` 行）。**不使用**
`launchPersistentContext`／`storageState`：每次全新 context，登入狀態不落地（免 cookie 檔視同密碼的風險）。
**但關閉 context 只清掉本機 cookie，網站伺服器端的登入狀態仍在，仍可能被算成一台上線裝置**，所以不能
當作滿足 FR-008：**伺服器端登出是必要步驟**（`finally` 中先走網站登出、驗證成功，再關 context；與
contracts/cli.md §4 一致）。登出失敗＝該次標記 `logged_out=0`、Telegram 通知，且下一次執行前先重試登出。帳密由 Python 從鑰匙圈讀出後**經 stdin 傳給子行程**，不放命令列參數與環境變數。
防自動化旗標、zh-TW、Asia/Taipei、隨機延遲 `rnd()`、`BLOCK_URL_RE` 軟／硬封鎖偵測沿用 flight scraper 寫法
（`flight_scraper.js:29,72,186-196,207`）。**登入／登出／fill 流程 repo 內沒有先例，須新寫**。
**Rationale**: 全新 context 避免本機留下可重用的登入憑證；與伺服器端登出**合併**才滿足「網站端不留登入狀態」。
代價是每次要重新登入——但本功能本就一天最多 1 次。
**Alternatives**: 持久 profile（少登入但會留登入、可能占裝置名額，spec 明確取捨為不超限優先）；純 HTTP
requests 登入（Python 無 requests 依賴、且不易模擬瀏覽器行為；未排除，視 P7 探查結果再議）。

## R4. 低頻上限、退避、重試

**Decision**: 常數寫在 `investanchors_import.py` 頂端：`MAX_ARTICLES_PER_RUN=5`、`MAX_LOGINS_PER_DAY=1`（PO 決定 2026-11-15：一天一次，見 R8）、
`DELAY_RANGE=(30,90)` 秒、`MAX_ATTEMPTS_PER_ARTICLE=3`、`BLOCK_BACKOFF_DAYS=1`。執行前先查 `import_runs`
表：當日登入次數已達上限、或 `blocked_until` 未到，**直接結束且不登入**。被擋跡象（連續 2 次逾時、
導向登入頁、非預期頁面）→ 寫 `blocked_until = now+1 天`＋Telegram。單篇失敗：`attempts += 1`，同次不重試；
達 3 → `abandoned`＋通知。**放寬任一常數須 PO 同意**（寫入 quickstart 與常數註解）。
**Rationale**: FR-007／FR-012／FR-015。狀態存 db 而非檔案，沿用 `flight_browser_usage.json` 的精神但可查詢。

## R5. 表格圖轉寫

**Decision**: 新 `article_transcribe.py`，用 `urllib` 呼叫視覺模型 HTTP API（repo 內**沒有任何 LLM 呼叫先例**）。
**不裝 SDK 的理由**：排程跑系統 `/usr/bin/python3`（3.9.6）、僅標準庫（requirements.txt 只有 yfinance），
新增套件會讓每次部署與 launchd 環境多一個失敗點。
起始模型：**`claude-haiku-5-5`**（不加日期後綴；PO 決定「成本最低且抽查合格」，據主對話提供：輸入 0.10／輸出
0.50 美元每百萬 token，Haiku 4.5 為 1／5）；**模型 ID 寫成可調的模組常數 `TRANSCRIBE_MODEL`**，升級或換模型
只改一處，並寫入 `article_image.transcribed_model` 以便辨識重轉對象。**此 ID 與價格我無法在本環境獨立查證
（我的環境清單只列到 Haiku 4.5），實作第一步須對照官方文件確認 ID 存在可用。**
金鑰存鑰匙圈 `stnd-investanchors`／`vision-api-key`，缺金鑰或額度不足 → 該圖標記 `untranscribed`，
文章照存。提示詞要求：只轉寫圖中可見數字與文字、看不清楚的格子寫 `?`、判斷「是否為表格」。
**資料庫只存轉寫內容，不存任何「機器轉寫」標示或路徑**（否則 `LIKE` 搜尋會被標示用字／路徑字串命中所有
文章）；標示在輸出層（`get_article`／搜尋片段）加上。
**實作時須對照官方文件確認的點**：(1) 該模型預設會思考，`max_tokens` 要留足；(2) **不要送非預設的
temperature／top_p／top_k**（會被拒）；(3) `{is_table, text}` 用**結構化輸出**，不自行解析自由文字；
(4) 回應 `stop_reason` 為 `refusal` 或 `max_tokens` 時，該圖一律標 `untranscribed`，不採用任何部分輸出。
**上線前抽查（FR-018／SC-007；PO 決定 2026-11-15）**：從 P6 取得的真實表格抽 **10 張**，轉寫結果由 **PO 本人逐格
確認**，PO 認可才採用目前模型；**PO 不認可則升級模型、再抽 10 張**（逐級升）。**不設百分比門檻**。補轉寫：`investanchors_import.py --retranscribe` 只讀本機
圖片檔、不登入網站（FR-017）。
**Rationale**: 既有慣例「圖交給對話中的 Claude 讀」（`us_stock_mcp_server.py:66-69`）不適用於無人值守排程，
故必須新增，這是本功能唯一的全新外部依賴與費用來源。
**Alternatives**: 本機 OCR（tesseract 對中文財測表的數字準確度未驗證；備選，若 API 成本或隱私不接受再評）；
只存圖不轉寫（違反 FR-016，PO 明確要求表格數字進 MVP）。**表格圖送第三方模型 API：PO 已於 2026-11-14 同意**
（需求基線 Q-016）；送出的只有表格圖本身，用途為 PO 個人使用的資料處理。

## R6. 搜尋實作（實測推翻了原先的 FTS5 假設）

**Decision**: **不用 FTS5**，用 `LIKE` 掃描：查詢字串以空白切成多個關鍵字，皆需出現（AND），搜尋範圍＝
標題＋全文＋所有圖片轉寫文字；片段取第一個命中處前後各約 60 字。
**Rationale（2026-11-15 在這台機器實測，Python 3.9.6／SQLite 3.51.0）**：FTS5 `trigram` tokenizer 對 3 字以上
OK，但 **2 字中文詞完全搜不到**（「環宇」→0、「財測」→0；僅「EPS」英文 3 字→1）。台股個股簡稱大量是 2
字（環宇、緯穎…），這會讓核心用例（SC-008）失效；`unicode61` 不切中文詞。語料規模預估數百～數千篇×數十
KB（≤百 MB 量級），`LIKE` 全掃在本機毫秒～數百毫秒，足夠。
**Alternatives**: FTS5 trigram＋對 <3 字查詢退回 LIKE（兩套邏輯、更複雜，無必要）；自行做中文 bigram 前處理
欄位（可行但為此規模過度設計）。**重新評估點**：若 P1 探查得到文章數 >5,000 或查詢明顯變慢，再改 bigram FTS。

## R7. 查詢介面（MCP）

**Decision**: 兩工具 `search_articles(query, limit=10)`、`get_article(article_id)`。台股 `server.py` 與
美股 `us_stock_mcp_server.py` **各自註冊一份、都讀同一個 `articles.db`**（台美強制各自獨立 Server，
`mcp.py:125-129`）；唯讀白名單 `server_readonly.py` 加入（供 Cline／stock-researcher）。兩個 Server 的資料目錄
解析各自開 `articles.db`，因為它不屬任一市場，路徑固定為同一 `data_dir` 下的 `articles.db`。工具回傳
文字；`get_article` 一併回傳圖片清單（本機檔路徑＋是否為表格＋轉寫狀態＋轉寫文字）。同步清單
（CLAUDE.md「常用查證點」）：`server.py` TOOLS＋call_tool、`server_readonly.py`、`us_stock_mcp_server.py`、
`test_pnl.py::test_tool_counts`（**48→50、29→31**）、
`test_traceability.py::test_tools_list_has_forty_eight`（:252-261，`assertEqual(len(names), 48)`→50，函式名與
docstring 同步並加入預期工具名；**2026-11-15 起初誤判此檔無斷言，經審查並開檔確認後更正**）、Mac 上 `~/.claude` 的 stock-researcher 白名單（**不在 repo**，PO 手動）。
**注意**：`test_claude_ai_connector.py:46-49` 斷言美股模組不含 `get_holdings` 且 names==TOOLS；新工具名
不得與台股工具衝突。

## R8. 排程

**Decision**: `com.alphavibe.investanchorsimport.plist`，樣式同 `statementimport.plist`（`/usr/bin/python3`、
`AlphaVibe-prod`、PATH 含 `/opt/homebrew/bin`、log 寫 `~/Library/Logs/alphavibe-investanchors*.log`、
**無** `RunAtLoad`／`KeepAlive`，靠 `StartCalendarInterval` 於喚醒後補跑一次）。**PO 決定（2026-11-15）：一天一次，
每晚 23:00**（取代原建議的 12:40、15:40，作廢），對應 `MAX_LOGINS_PER_DAY=1`。既有排程時段：02:00、03:30、
03:45、04:00、06:00、07:45、09:30、17:00、20:15、23:15、週一 10:00；23:00 不與任一時段相同。
**與 23:15 `statementimport` 的重疊評估**：最壞情況單次 = 登入＋5 篇×最長 90 秒間隔（≈7.5 分鐘）＋圖片下載
與轉寫（每篇數秒～數十秒，且最後一篇之後無間隔）＋登出，保守估 10～12 分鐘，**可能跨到 23:15 而與之並行**。
結論：**並行無衝突、不需錯開**——兩者各自獨立行程；資料庫不同（`articles.db` vs `alphavibe.db`）；唯一共用的是
Gmail IMAP，但各開各的唯讀連線（皆 `readonly=True`／`BODY.PEEK`），Gmail 允許多連線；Chromium 與 qpdf 的
資源負載在本機可忽略。launchd 對不同 label 的 job 不會互相等待。若實測發現互相拖慢再改為 22:30。
**睡眠補跑風險**：Mac 在 23:00 睡眠時，launchd 於喚醒後補跑一次，實際時間可能落在 PO 正在使用網站的時段
（FR-008 兩台上限）；探查 P2b 與上線驗證期須觀察，必要時於程式內加「非 22:30–次日 06:00 不啟動」的時間窗守衛
（會使補跑延到下一個 23:00，視為可接受）。每次執行即使無觸發也會跑信箱檢查（便宜、唯讀），不等於登入。
**影響（歷史回補速度）**：每日最多登入 1 次、每次最多 5 篇，回補速度為**每天最多 5 篇**。**PO 2026-11-15
決定回補範圍只含最近半年（見 R11）**；PO 提供網站發文約每週 2～5 篇，半年約 50～130 篇，**以每天 5 篇計約
11～26 天**。實際篇數由探查依清單日期估算（輸出「半年內篇數」與每頁篇數）後回報 PO 校正。新文章在回補期間與回補共用同一個每日 5 篇額度，**新文章（有通知信者）優先於回補**。
健康檢查：`check_scheduled_jobs.py` 新增 `check_investanchors_import()`（讀 `import_runs`，比照
`check_statement_import`）。

## R9. 內容更新與資料生命週期

**Decision**: 只增不刪；已 `fetched` 的文章**不因網站改文而覆寫**（第一版全文為準），不做更新偵測。
**Rationale**: spec 標為 plan 決定；偵測更新需重新開啟已匯入文章，直接違反 FR-003「不重複開啟」與低頻。
若 PO 日後要更新機制，另開 feature。

## R10. 憑證與祕密

**Decision**: 新 service `stnd-investanchors`，accounts：`email`、`password`、`vision-api-key`。擴充
`keychain_secrets.py` 成可指定 service（保持舊呼叫不變，009 測試不得受影響）。存入指令與 009 相同規約：
`security add-generic-password -U -s stnd-investanchors -a <固定名稱> -w`，**`-a` 後是固定名稱、`-w` 後不接
值**（009 已發生過誤填）；驗證只用 `find-generic-password ... >/dev/null && echo ok`；**禁止**
`dump-keychain`／`-w`／`-g`。.gitignore 目前**沒有**祕密檔規則；本設計無任何祕密落地檔，探查輸出目錄
`poc/data/articles_probe/` 已在被忽略的 `poc/data/` 之下。

## R11. 回補範圍：只補最近半年（PO 2026-11-15）

**Decision**: 回補只處理「清單發布日期在回補**首次啟動日**往前六個月內」的文章；更早的記為 `deferred`（只存
ID、標題、日期，不開啟）。清單從最新往舊翻，**讀到整頁都早於截止日即停**，不再翻更舊的頁——這比全量回補
更低頻，也少開很多頁。截止日存於 `backfill_state.cutoff_date`，啟動後固定。
**清單日期的使用區分（重要）**：spec 與 R1 說「清單日期不可靠，不能作為新舊／是否已抓的依據」——這仍然成立，
新舊與是否已抓一律只看文章 ID。此處清單日期只用來做**半年粗篩**：截止日附近誤差數天、多抓或少抓一兩篇，
不影響目的，可接受。置頂公告（日期在未來）先依標題前綴略過，不參與停止判斷。
**之後擴大範圍**：`investanchors_import.py --backfill-since <YYYY-MM-DD>`（contracts/cli.md §1）把截止日往前
放寬、重新開啟回補，並把落在新舊截止日之間的 `deferred` 轉回 `discovered`，仍依每日 5 篇慢慢補；放寬範圍
須 PO 同意。
**Alternatives**: 全量回補（PO 已排除，天數與帳號風險較高）；用文章 ID 區間代替日期（ID 與日期的單調關係
未驗證，列為探查項 P8）。
**探查加項（P8）**：依清單日期估算「半年內篇數」與每頁篇數；並檢查文章 ID 是否隨時間單調遞增（若是，日後
可用 ID 做更穩的截止判斷）。

## 風險摘要

1. 帳號被停用（兩台上限／行為偵測）→ R3 全新 context＋R4 上限；探查規約最小化。
2. 站方改版 → DOM 解析集中在 scraper 一處，取不到內文就標失敗不寫殘缺（FR-013）。
3. 轉寫不準 → 標示＋原圖＋上線前抽 10 張由 PO 本人逐格確認。
4. 把付費內容送第三方模型 API → PO 已於 2026-11-14 同意（Q-016，R5）。
5. 歷史回補慢（每天最多 5 篇）→ 範圍限半年（R11），約 11～26 天；實際篇數待探查校正後回報 PO（R8）。
