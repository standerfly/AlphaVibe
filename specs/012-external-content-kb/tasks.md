---

description: "外部內容知識庫（012）任務清單"
---

# Tasks: 外部內容知識庫（YouTube／Podcast／文章）

**Input**: `/specs/012-external-content-kb/` 下的 plan.md、spec.md、research.md、data-model.md、contracts/（tools.md、inbox-file-format.md）、quickstart.md
**Prerequisites**: plan.md、spec.md（皆已就緒）

**Tests**: 計畫（plan.md「Source Code」）已明訂測試檔，且既有守門測試必須同步更新，故本清單**包含測試任務**；單元測試一律用獨立 data dir，絕不指向 `poc/data/`。

**Organization**: 依使用者故事分階段；US1＋US2＋Phase 5（接線）構成可用的 MVP。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可平行（不同檔案、無未完成的相依）
- **[Story]**: 對應 spec.md 使用者故事（US1～US6）
- 所有路徑皆自 repo 根目錄起算；程式在 `poc/kb-mcp/`，測試在 `poc/kb-mcp/tests/`
- 程式一律保持 **Python 3.9 相容**（不用 `match`、`X | Y` 型別語法）；不新增第三方套件

---

## Phase 1: Setup（共用前置）

- [x] T001 **（需先取得 PO 同意；會改寫本分支歷史）** 將本分支的文件 commit rebase 到 `origin/function/alphavibe` 之上：先 `git status`／`git log --oneline origin/function/alphavibe..HEAD` 確認只有文件 commit（`docs/spec-intake/`、`specs/`、`.specify/feature.json`）；衝突預期只在 `docs/spec-intake/index.md`；完成後確認 `poc/kb-mcp/article_store.py`、`article_tools.py`、`server_readonly.py` 存在於工作樹。不要碰 `poc/data-test-articles/`、`poc/kb-mcp/scraper/`
- [x] T002 在 rebase 後的乾淨樹上跑一次基準：`python3 -m unittest discover -s poc/kb-mcp/tests`，記錄通過／失敗數字（改動前後要能對得上）；若有既有失敗，記錄為基準，不歸咎本功能；**基準（2026-11-25，rebase 後、僅既有測試）**：Ran 2340 tests，FAILED（failures=6, errors=4, skipped=3）。皆與本功能無關：`test_us_stock_price_client` 4 個（本機 Python 無 `yfinance`）、`test_article_manual_transcribe` 與 `test_transcription_pipeline` 共 4 個（macOS `/var`→`/private/var` 等路徑／環境斷言）、`test_flight_search.SampleDatesTest` 1 個（日期敏感）、`test_transcription_pipeline.SafetyGatesTest` 1 個。之後比對：這 10 個以外不得新增失敗
- [x] T003 [P] 確認測試慣例：讀 `poc/kb-mcp/tests/test_article_store.py`（或同類）的暫存 data dir 寫法，沿用；在 `poc/kb-mcp/tests/` 確認新測試檔命名 `test_external_content_*.py` 可被 `discover` 找到

---

## Phase 2: Foundational（阻擋所有使用者故事）

**⚠️ 完成前不得開始任何使用者故事**

- [x] T004 [P] 建立 `poc/kb-mcp/external_content_identity.py`：`source_key(url, source_type, guid=None)`、`body_sha256(text)`（空白正規化後）、YouTube 以**網址主機精確比對**判斷（`youtube.com`／`www.`／`m.`／`music.youtube.com`／`youtu.be`，不得後綴比對）、ID 來自 `watch?v=`／`/shorts/`／`/live/`／`/embed/`／`youtu.be/`、忽略 `si`／`feature`／`t`／`start`／`list`／`utm_*`／`pp`；Podcast 有 guid → `podcast:guid:<guid>`；一般網址規則（https、小寫主機去 `www.`、去 fragment、去追蹤參數、其餘 query 依鍵排序保留、去尾斜線；Apple Podcasts 保留 `i=`）；無法得出 key 時拋出帶原因的例外。規則見 contracts/inbox-file-format.md「身分規則」
- [x] T005 [P] 撰寫 `poc/kb-mcp/tests/test_external_content_identity.py`：youtu.be／watch?v=／shorts／live／embed／手機版／music 與帶 `si=`、`t=` 的寫法收斂為同一 key；`youtube.com.evil.com` 不被當 YouTube；source_type 標成 podcast 但網址是 YouTube 仍走 YouTube 規則；無法判斷 ID 的 YouTube 網址拋錯；一般網址追蹤參數去除、其餘 query 保留；guid 優先；雜湊對空白差異穩定
- [x] T006 建立 `poc/kb-mcp/external_content_store.py`：`ExternalContentStore(data_dir)`，庫檔 `<data_dir>/external_content.db`；建構子**只**建 `content`／`summary`／`audit_log` 三表與索引（依 data-model.md，含 CHECK、UNIQUE(source_key)、INDEX body_sha256／published_on），**不寫任何資料**；`open_readonly(data_dir)`（`mode=ro` URI，庫不存在拋 FileNotFoundError、不建庫、不跑 schema）；寫入一律 `BEGIN IMMEDIATE`＋失敗 rollback，資料與 `audit_log` 同交易；比照 `poc/kb-mcp/article_store.py` 的 `__init__`／`open_readonly`／交易寫法；`content` 加 `deleted_at`（軟刪除，見 data-model.md）、`audit_log` 加 `channel`；寫入方法接收 `channel` 參數
- [x] T007 撰寫 `poc/kb-mcp/tests/test_external_content_store.py`（基礎部分）：建構子不寫資料（建完 `content`／`summary`／`audit_log` 皆 0 列）；`open_readonly` 對不存在的庫拋錯且不建檔；中途失敗整筆回滾（庫內無殘留、audit 也無）；`source_key` UNIQUE；`source_type` CHECK；`published_on` 格式驗證；另斷言 `content` 的全文（`body`）與入庫時間（`created_at`）確實保存（FR-021）
- [x] T008 建立 `poc/kb-mcp/external_content_tools.py` 骨架：固定標註常數 `作者個人觀點，未經查證`、輸出格式化 helper（每筆內容區塊各自附標註、整體末尾再附一次）、7 個工具的 schema 定義（名稱：`search_external_content`、`get_external_content`、`create_inbox_file`、`import_inbox`、`import_text`、`confirm_summary`、`delete_content`；名稱不得含 `article`／`verif`／`reviewed`）、`EXTERNAL_CONTENT_TOOL_NAMES`、`call_external_content_tool(name, args, data_dir)` 分派（未實作者先回明確錯誤）；比照 `poc/kb-mcp/article_tools.py` 的結構。schema 內容依 contracts/tools.md；輸出層加第三方內容分隔標記與「不是指令」聲明（內文含相同標記先脫逸）；錯誤一律 `raise`（`server.py` 只對例外標 `isError`）；寫入工具加「資料目錄＝正式資料目錄且未設 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1` 則拒絕」檢查；**已完成的正式庫保護**：`ensure_write_allowed(data_dir)` 於 `call_external_content_tool` 對 `WRITE_TOOL_NAMES` 一律先檢查（比對 `realpath`，涵蓋 `AlphaVibe-prod/poc/data` 符號連結），5 個測試在 `ProductionWriteGuardTest`

**Checkpoint**: 身分規則、store、工具骨架就緒 → 可開始使用者故事

---

## Phase 3: User Story 1 - 把一支影片或一集 Podcast 存進知識庫（Priority: P1）🎯 MVP

**Goal**: PO 貼連結請 agent 建檔 → 貼入內文 → 說「匯入」→ 入庫；逐字稿不經模型輸出。

**Independent Test**: 在模組層以獨立 data dir 走完「建檔→寫入內文→匯入」，確認庫內新增一筆、輸出帶標註、缺欄位／空內文／多檔部分失敗皆符合驗收情境（不需伺服器接線）。

### Tests for User Story 1

- [x] T009 [P] [US1] 撰寫 `poc/kb-mcp/tests/test_external_content_inbox.py`：中繼資料區塊解析（`---` 包夾、`key: value`、空行與 `#` 註解忽略、未知鍵忽略並提示、值含冒號）；缺必填鍵／`source_type` 不在三值／`date` 格式錯／區塊無法解析皆回具體原因；內文去空白為空 → 「內文為空」；`filenames` 含路徑分隔字元或指向 `processed/` 被拒；realpath 守衛（含 `/var`→`/private/var`、符號連結逃出 inbox）；只掃最上層 `.md`／`.txt`，其他副檔名列入 `skipped_unsupported`；單檔上限 2,000,000 字元；缺 `url`（FR-015 缺連結）與 `url` 非 http／https 皆回具體原因；**符號連結案例**：資料目錄本身是符號連結（模擬 `AlphaVibe-prod/poc/data`），inbox 根目錄與檔案兩邊都 realpath 後比對仍能正常讀取；搬入 `processed/` 同名檔不覆蓋（加序號）；內文開頭出現第二個 `---` 區塊 → 失敗並提示
- [x] T010 [P] [US1] 撰寫 `poc/kb-mcp/tests/test_external_content_metadata.py`：YouTube 中繼資料擷取的**解析函式**以固定樣本（oEmbed JSON、網頁含 `uploadDate`）測試；SSRF 防護——非 https、非精確 YouTube 主機、跨主機轉址、回應超過 2 MB 皆拒絕；抓不到欄位時回缺欄位清單、**絕不猜測**；網路呼叫以注入的假 fetcher 取代，不實際連網
- [x] T011 [P] [US1] 在 `poc/kb-mcp/tests/test_external_content_tools.py` 撰寫 US1 部分：`create_inbox_file`（來源已存在→不建檔告知既有、缺欄位→回清單不建檔、齊全→在 inbox 最上層建檔內文空白並回完整路徑、檔名衝突不覆蓋、寫入失敗不留半檔）；`import_inbox`（單檔成功入庫並搬 processed、缺欄位／格式錯／空內文失敗且維持待處理、多檔其中一檔失敗其餘照常、inbox 空回「資料匣沒有待匯入檔案」、失敗檔維持待處理）；`import_text`（成功、缺欄位、超過上限回「內容過長」且不入庫）；每條成功輸出含標註；FR-006 兩種進件規則一致；成功匯入寫入一筆 `audit_log(import)`（FR-020）；`import_inbox`／`import_text` 的輸出含「下一步」提示並提醒 agent 逐檔提出摘要草稿、草稿不入庫（FR-017）；`import_text` 工具說明含「耗輸出 token」字樣（FR-005）；`import_inbox` 先建立 `inbox/` 與 `inbox/processed/`（若不存在）；US1-6：用 AI Studio 格式的完整檔（含中繼資料區塊）放入 inbox 後匯入，與建檔流程結果一致；`create_inbox_file`：資料匣已有同 `source_key` 的待處理檔 → 不建新檔、回該檔路徑；匯入途中檔案已被搬走 → 不中止整批；寫入工具在資料目錄為正式目錄且無旗標時被拒；稽核 `channel` 正確記錄

### Implementation for User Story 1

- [x] T012 [US1] 建立 `poc/kb-mcp/external_content_inbox.py`：區塊解析、檔案掃描（最上層、副檔名過濾、`skipped_unsupported`）、讀檔 realpath 守衛（只讀 `<data_dir>/inbox/` 內）、`filenames` basename 檢查、建檔（檔名規則見 contracts/inbox-file-format.md、不覆蓋、失敗不留半檔）、成功後搬入 `inbox/processed/`；首次使用時建立 `<data_dir>/inbox/` 與 `<data_dir>/inbox/processed/`；inbox 根目錄與檔案**都**用 `os.path.realpath` 比對；偵測內文開頭的重複中繼資料區塊；搬檔同名加序號；Apple Podcasts 身分取「節目 id＋單集 i」；檔案被搬走時容忍
- [x] T013 [P] [US1] 建立 `poc/kb-mcp/external_content_metadata.py`：僅 YouTube 的中繼資料自動填（oEmbed 標題／頻道＋網頁 `uploadDate`），逾時 10 秒、SSRF 防護（https、精確主機比對、以 11 碼 ID 重組標準網址、禁止跨主機轉址、回應上限 2 MB）、fetcher 可注入；拿不到的欄位明確標示缺少
- [x] T014 [US1] 在 `poc/kb-mcp/external_content_store.py` 實作寫入核心：`add_content(...)`（驗證必填與格式 → 以 `source_key` 檢查重複〔**先判斷重複、再驗內文非空、再算雜湊**〕→ 單一交易寫入 `content`＋`audit_log(import)`）；重複時回既有內容資訊、不寫入；`find_by_source_key`；**業務層驗證（Phase 2 驗收揭露）**：內文非空用 `str.strip()` 判斷（SQLite CHECK 的 trim 只去 space／tab／LF／CR，全形空白會通過）；`published_on` 用 `datetime.date.fromisoformat` 驗為真實日曆日（CHECK 只擋形狀，`2026-02-30` 會通過）；稽核 `detail` 不得含全文，並以測試斷言 `audit_log.detail` 不含 body 內容；`PRAGMA foreign_keys` 預設關閉，需要 FK 時於連線設定 `ON` 或由業務層檢查
- [x] T015 [US1] 在 `poc/kb-mcp/external_content_tools.py` 實作 `create_inbox_file`、`import_inbox`（US1 範圍：`on_duplicate=ask` 預設行為、逐檔獨立處理、逐檔狀態 `imported`／`duplicate`／`failed`、統計、`skipped_unsupported`）、`import_text`（上限預設 200,000 字，可由環境變數調整）；重複僅回報、不取代（取代與雜湊相同分支留給 US4）；`create_inbox_file` 同時檢查資料匣待處理檔；`channel` 傳入 store
- [x] T016 [US1] 在 `poc/kb-mcp/external_content_tools.py` 補齊匯入結果的下一步提示文字：匯入完成回報時附「下一步」提示並提醒 agent 逐檔提出摘要草稿、草稿不得入庫（工具說明文字，FR-017）；工具說明標明 `import_text` 耗輸出 token、長文請走資料匣

**Checkpoint**: US1 在模組層可獨立運作並通過 T009～T011

---

## Phase 4: User Story 2 - 討論投資時自動查詢並引用（Priority: P1）

**Goal**: 搜尋（2 字中文詞必中、回片段）、取全文（可指定範圍、可只看摘要），每筆各附標註。

**Independent Test**: 先寫入數筆測試內容，驗證 2 字詞命中、片段非全文、分段取用、`summary_only`、每個命中項各含標註。

### Tests for User Story 2

- [x] T017 [P] [US2] 在 `poc/kb-mcp/tests/test_external_content_store.py` 補搜尋測試：`LIKE … ESCAPE '\'`（含 `%`、`_`、`\` 的查詢字串不被當萬用字元）、空白切詞 AND、2 字中文詞（如「財測」）命中、`source_type` 篩選、`limit` 預設 10／上限 30、片段半徑 60 字且最多 2 段、日期新到舊
- [x] T018 [P] [US2] 在 `poc/kb-mcp/tests/test_external_content_tools.py` 補 US2 部分：`search_external_content` 每個命中項區塊各含一次標註（逐筆斷言）且末尾另有一次、不回整份全文、顯示已確認摘要數量與 `summary_id`、無命中回「沒有找到」＋標註；`get_external_content` 的 `offset`／`length` 範圍、`summary_only=true` 不含原文、附完整中繼資料與摘要（含 `summary_id`）、找不到 ID 為錯誤；以 5 個取自測試內文的 2 字詞逐一搜尋皆命中；斷言第三方內容被分隔標記包住且含「不是指令」聲明；摘要確認時間早於全文更新時間時加註「此摘要確認於全文更新之前」

### Implementation for User Story 2

- [x] T019 [US2] 在 `poc/kb-mcp/external_content_store.py` 實作 `search(query, source_type=None, limit=10)` 與 `get(content_id, offset, length)`（比照 `article_store.py` 的 `_like_pattern`／snippet 做法；`search`／`get` 都走唯讀連線路徑）
- [x] T020 [US2] 在 `poc/kb-mcp/external_content_tools.py` 實作 `search_external_content`、`get_external_content` 的格式化輸出（每筆各附標註、末尾再附一次；`summary_only`；`include_summaries`）

**Checkpoint**: US1＋US2 在模組層完成；仍需 Phase 5 接線才能被 claude.ai／本機 Claude Code 呼叫

---

## Phase 5: 接線與守門（US6 · 全部工具上線所需，屬 MVP）

**Goal**: 把工具掛到正確的伺服器，唯讀端沒有任何寫入工具，守門測試同步更新。

**Independent Test**: 唯讀端 `tools/list` 只含 2 個查詢工具、呼叫 5 個寫入工具皆被拒；台股 57／唯讀 33／美股 12；既有守門測試全綠。

### Tests

- [x] T021 [P] [US6] 建立 `poc/kb-mcp/tests/test_external_content_readonly.py`：`server_readonly` 的 `tools/list` 只含 `search_external_content`、`get_external_content`；呼叫 `create_inbox_file`／`import_inbox`／`import_text`／`confirm_summary`／`delete_content` 皆回「沒有授權呼叫寫入工具」類錯誤；外部內容工具名稱不含 `article`／`verif`／`reviewed`；另加美股實查（US2-5）：以同一關鍵字分別經 `server.py` 與 `us_stock_mcp_server.py` 的 `call_tool` 查詢同一份測試庫，確認兩邊都查得到同一筆（此測試在 T025 接線後才會轉綠）
- [x] T022 [P] [US6] 更新守門測試：`poc/kb-mcp/tests/test_pnl.py`（`len(server.TOOLS)` 50→57、`len(READONLY_TOOLS)` 31→33）、`poc/kb-mcp/tests/test_traceability.py`（50→57，建議順手把測試名 `test_tools_list_has_fifty` 改為不含數字）、`poc/kb-mcp/tests/test_us_stock_mcp_server.py`（名稱集合加入 2 個查詢工具；美股工具總數 10→12）

### Implementation

- [x] T023 [US6] 修改 `poc/kb-mcp/server.py`：`TOOLS` 併入 7 個外部內容工具 schema；`call_tool` 開頭攔截外部內容工具名稱並交給 `call_external_content_tool`（比照 article 工具的 `server.py` 掛法）；data dir 沿用現有解析
- [x] T024 [US6] 修改 `poc/kb-mcp/server_readonly.py`：`READONLY_TOOLS` 白名單加入 `search_external_content`、`get_external_content`（**寫入 5 個不得加入**）；同步檔內註解的工具數字
- [x] T025 [US6] 修改 `poc/kb-mcp/us_stock_mcp_server.py`：只併入 2 個查詢工具 schema 與 `call_tool` 分派（寫入工具不掛美股端）
- [x] T026 [US6] 跑接線後的守門測試與全套：`python3 -m unittest discover -s poc/kb-mcp/tests`，與 T002 基準比對（失敗數不得增加；新增測試全綠）；**結果（2026-11-25）**：Ran 2540 tests（基準 2340＋本功能 200），FAILED（failures=6, errors=4, skipped=3），失敗名單與 T002 基準逐項相同，未新增任何失敗

**Checkpoint**: 程式面 MVP 完成——US1＋US2 已掛上伺服器、守門測試全綠（尚未對 claude.ai 生效，需 T037 專案指示與 T045 部署）

---

## Phase 6: User Story 3 - 摘要必須經 PO 同意才入庫（Priority: P2）

**Goal**: 只有帶 PO 明確同意的 `confirm_summary` 才會寫入摘要；草稿從不入庫。

**Independent Test**: 對一筆內容分別嘗試「無確認／空原話／確認」，只有確認會寫入；唯讀端無此工具。

### Tests for User Story 3

- [x] T027 [P] [US3] 在 `poc/kb-mcp/tests/test_external_content_store.py` 補摘要測試：`add_summary`（`confirmed`、`po_quote` 非空、`confirmed_at`、audit `summary_confirm` 同交易）、`revise`（同交易撤回舊則＋新增新則，任一步失敗舊摘要不受影響）、`revoke`（status 變 `revoked`，查詢不再出現，列保留供稽核）、內容軟刪除後摘要不再被查詢（列保留）
- [x] T028 [P] [US3] 在 `poc/kb-mcp/tests/test_external_content_tools.py` 補 US3 部分：缺 `po_confirmed=true` 或原話為空 → 拒絕且庫內無摘要；`confirm`／`revise`／`revoke` 成功路徑；多檔時各筆獨立；摘要出現在 `get_external_content` 並與原文分段標示、`summary_id` 可得；**任何路徑在未確認時寫入摘要的次數為 0**；`revise`／`revoke` 缺 `summary_id` 回明確錯誤；**`revoke` 也必須帶 `po_confirmed=true` 與非空原話**（缺則拒絕且不寫入，稽核 `summary_revoke` 記錄原話）

### Implementation for User Story 3

- [x] T029 [US3] 在 `poc/kb-mcp/external_content_store.py` 實作 `add_summary`、`revise_summary`、`revoke_summary`（BEGIN IMMEDIATE、audit 同交易、`po_quote` 必填）；每個稽核寫入點（`summary_confirm`／`summary_revise`／`summary_revoke`）都要有測試斷言 `detail` 不含摘要全文以外的敏感內容（只含 `po_quote`、`summary_id`、標題）
- [x] T030 [US3] 在 `poc/kb-mcp/external_content_tools.py` 實作 `confirm_summary`（`action`＝`confirm`｜`revise`｜`revoke`）；工具說明寫死「僅在 PO 明確說同意後呼叫；草稿、PO 拒絕、沉默一律不得呼叫」，並在說明中註明這是遵循度保證

**Checkpoint**: US3 獨立可測

---

## Phase 7: User Story 4 - 重複來源與更新全文（Priority: P2）

**Goal**: 同一來源（任何連結寫法）不重複入庫；PO 可選取代全文（保留已確認摘要）或放棄；已處理檔不重複入庫；同內容不同來源只警告。

**Independent Test**: 以三種連結寫法重複匯入同一影片，庫內只有 1 筆；取代後摘要仍在。

### Tests for User Story 4

- [x] T031 [P] [US4] 在 `poc/kb-mcp/tests/test_external_content_tools.py` 補 US4 部分：重複回 `duplicate`（附既有 ID 與標題）；`on_duplicate=replace` 取代 `body`／`body_sha256`／`updated_at`、保留已確認摘要、寫 `replace` 稽核、檔案搬 processed；`skip` 不寫入並搬 processed；**`import_inbox` 的 `replace`／`skip` 未搭配 `filenames` 被拒**；`replace`／`skip` 對非重複檔無影響（仍正常入庫）；重複且雜湊相同 → `already_processed` 並搬 processed；模擬「DB 已提交但搬檔失敗」後再匯入 → 回 `already_processed` 並補搬、不重複入庫；`imported` 與 `duplicate` 都附 `same_body_elsewhere`；`import_text` 的 `ask`／`replace`／`skip`／相同雜湊各路徑；`create_inbox_file` 對已存在來源不建檔；已處理檔留在 inbox 再說「匯入」不重複入庫；重複且 PO 尚未決定的檔案維持待處理；SC-004：三種寫法重複匯入庫內只有 1 筆；重複檔內文為空且 `on_duplicate=ask` 仍回 `duplicate`（去重在驗內文之前）；`replace` 搭空內文回 `failed`「內文為空」且既有內容不變（工具層）
- [x] T032 [P] [US4] 在 `poc/kb-mcp/tests/test_external_content_store.py` 補：`replace_body`（只更新 body／雜湊／updated_at、summary 不動、audit 同交易、空內文拒絕）、`find_same_body(sha, exclude_key)`

### Implementation for User Story 4

- [x] T033 [US4] 在 `poc/kb-mcp/external_content_store.py` 實作 `replace_body`、`find_same_body`；`add_content` 結果附 `same_body_elsewhere`
- [x] T034 [US4] 在 `poc/kb-mcp/external_content_tools.py` 完成 `import_inbox`／`import_text` 的重複分支：`ask`／`replace`／`skip`、`already_processed`（雜湊相同）、`replace`／`skip` 在 `import_inbox` 須搭配 `filenames`（`import_text` 不受此限）、搬檔失敗的補搬邏輯、`same_body_elsewhere` 輸出

**Checkpoint**: US4 獨立可測

---

## Phase 8: User Story 5 - 刪除與撤回（Priority: P3）

**Goal**: 刪除單筆需 PO 明確確認；撤回／修改摘要走 US3 的 `confirm_summary`。

**Independent Test**: 缺確認的刪除被拒；確認後內容軟刪除（摘要隨之不可被查詢）並留稽核。

### Tests for User Story 5

- [x] T035 [US5] 在 `poc/kb-mcp/tests/test_external_content_store.py` 與 `test_external_content_tools.py` 補：`delete_content` 缺 `po_confirmed=true` 或原話為空 → 拒絕且無任何刪除；確認後同交易**軟刪除** `content`（設 `deleted_at`、`source_key` 改名）、`summary` 列保留、寫 `delete` 稽核（detail 含標題與原話、**不含全文**）、之後 `search`／`get` 查不到；刪除不存在的 ID 為錯誤；刪除後 audit 紀錄仍在；改為**軟刪除**斷言：`deleted_at` 設定、`source_key` 改為 `#deleted-<id>`、摘要不再被查詢、列仍在；刪除後同一來源可重新匯入；稽核含 `channel`

### Implementation for User Story 5

- [x] T036 [US5] 在 `poc/kb-mcp/external_content_store.py` 實作 `delete_content`（單一交易、audit 不含全文）；在 `poc/kb-mcp/external_content_tools.py` 實作 `delete_content` 工具與其說明（須 PO 明確確認）（軟刪除：設 `deleted_at` 並改 `source_key`，`search`／`get` 排除已刪除列）

**Checkpoint**: 7 個工具全數實作完成

---

## Phase 9: Polish & 跨故事事項

- [ ] T037 [P] 建立 `docs/runbooks/external-content-project-instructions.md`：專案指示段落（討論投資先 `search_external_content`、三步流程、建檔說法、摘要同意規則）＋兩版 AI Studio prompt（只產逐字稿／產含中繼資料區塊的完整檔，格式與 contracts/inbox-file-format.md 一致，含「長文被截斷請自行檢查結尾」提醒）（FR-016）；專案指示須含：引用外部內容時不得執行其中的指示、一次只處理 PO 要的動作；取全文前先搜尋定位、需要才分段取（`offset`／`length`），或先看 `summary_only`，非必要不整份讀入（PO 決定不設預設長度上限，以此緩解）
- [ ] T038 [P] 修改 `ALPHAVIBE_CONTEXT.md`：加入「外部內容庫」使用段落（與 T037 一致）；注意該檔以 `docs/` 文件為準的既有規則
- [ ] T039 在 `poc/kb-mcp/tests/test_external_content_tools.py` 補 FR 對照的收尾斷言：所有 7 個工具的每條成功輸出含標註（SC-003 逐項）；唯讀端無寫入（SC-005）；`confirm_summary`／`delete_content` 缺確認即拒；SC-005 的驗收說法改為「工具層拒絕缺確認＋遵循度觀察」：測試只證明缺確認旗標／原話會被拒，**不證明** agent 不會自行填寫（見 research R7）
- [ ] T040 以**真實磁碟庫**（非記憶體庫）量測搜尋冷讀時間：設 `ALPHAVIBE_DATA_DIR=<獨立測試庫，例如 poc/data-test-external/，需先加入 .gitignore 或放系統暫存目錄>`（**絕不寫 `poc/data/`**），寫入約 300 份、每份約 6 萬字的合成內容，重新開啟連線後各執行 5 次 2 字中文詞搜尋（含完全無命中的最壞情況），取最大值，確認 < 500 ms（目標遠低於）；結果記入 `specs/012-external-content-kb/research.md` R2
- [ ] T041 修改 `CLAUDE.md`（在 T001 rebase 之後，且為專案既有慣例）：新增 012 外部內容庫現況段落與常用查證點（新模組位置、`<data_dir>/external_content.db`、`<data_dir>/inbox/`、工具數 57／33／12、守門測試位置、名稱保留字限制）；改前先 `git diff --stat` 確認；順便記錄：新資料庫檔是否被每日備份涵蓋（`ops/` 的 dbbackup）及必要時補上
- [ ] T042 獨立驗收（**不得由實作者自驗**）：派 fresh agent 依 spec FR-001～021 與 Acceptance Scenarios、contracts 逐條驗證實作；驗收 prompt 須含否決條件（任一 FR 無對應實作或測試、測試實際未跑、唯讀端出現寫入工具、輸出缺標註）。結果與修正記入 `specs/012-external-content-kb/`
- [ ] T043 **（需 PO 提供 EP466 逐字稿檔案）** 端到端驗收：本機以 `create_inbox_file` 貼 EP466 連結 → 取得路徑 → 貼入逐字稿 → `import_inbox`；以 5 個取自內文的 2 字詞搜尋全數命中且含標註；三種連結寫法重複只有 1 筆；用唯讀端確認只有 2 個查詢工具（quickstart.md 驗證步驟 1～4）；**一律在獨立測試庫執行**（`ALPHAVIBE_DATA_DIR=<獨立測試庫>`，資料匣與庫都落在該目錄）；若 PO 要把 EP466 寫入正式庫，須另行取得 PO 同意並設 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`
- [ ] T044 **實測任務**：量測 claude.ai／ngrok 單次工具呼叫可傳的字數上限（只影響 `import_text` 上限與提示文字，結果回填 `external_content_tools.py` 預設上限與 research R9）；以多支 YouTube 影片驗證 `uploadDate` 擷取穩定度，失效時確認降級為問 PO；另量 `get_external_content` 回傳大筆全文（例如 5 萬、20 萬字）時 claude.ai 是否出錯或截斷，結果記入 research R9；**順序**：T044 的「呼叫上限」量測須在 T045 部署之後、或以本機經 ngrok 公開網址直接對 `/mcp/<token>` 發 `tools/call` 量測（逐步加大 `import_text` 內文：1 萬、5 萬、10 萬、20 萬字，記錄成功／失敗邊界）；`uploadDate` 以至少 10 支不同影片（含不同語言頻道）驗證，成功率 ≥ 9/10 視為及格，否則維持「抓不到就問 PO」的降級並於 research R5 註明
- [ ] T045 **（部署；對外動作，需 PO 當場同意）** 依 quickstart.md「部署」：把 2 個新查詢工具補進 Mac 上 `~/.claude` 的 stock-researcher 白名單（不在 repo）；合併 PR 後以 `AlphaVibe-prod` 流程部署並重啟服務；確認 claude.ai 兩個連接器 `tools/list` 台股多 7 個、美股多 2 個；請 PO 把更新後的專案指示貼進 claude.ai 專案；在 claude.ai 專案實測 agent 是否主動搜尋（spec Scenario 11，遵循度驗證）；部署時並確認 `ops/` 備份是否涵蓋 `external_content.db`

- [ ] T046 **（部署後；需 PO 參與）** claude.ai 主路徑端到端驗收（SC-007 與 SC-001 的「引用」）：PO 在 claude.ai 的 AlphaVibe 專案（台美連接器皆啟用，專案指示已更新）依序走「貼連結請建檔 → 在 Mac 開檔貼內文 → 說『匯入』→ 對摘要說『同意』」，過程以 `~/.claude` 或 claude.ai 對話記錄檢查：(a) agent 輸出**不含**整份逐字稿；(b) 正式環境（符號連結資料目錄）下建檔與匯入皆成功；(c) 之後談 3 個庫內有的主題，至少 2 個 agent 主動搜尋並引用且帶標註（遵循度判準：3 取 2）；(d) PO 不看文件即可完成。結果記入 `specs/012-external-content-kb/`

---

## Dependencies & Execution Order

### Phase 相依

- **Phase 1（Setup）**：T001 需 PO 同意，且為其餘所有任務前提（程式要建在 `function/alphavibe` 之上）；T002、T003 在 T001 之後。
- **Phase 2（Foundational）**：依賴 Phase 1；**阻擋所有使用者故事**。T004／T005 可平行；T006 依賴 T004；T007 依賴 T006；T008 依賴 T004、T006。
- **US1（Phase 3）**、**US2（Phase 4）**：依賴 Phase 2；兩者彼此獨立，可平行（皆改 `external_content_tools.py`／`external_content_store.py`，同檔任務需循序合併）。
- **Phase 5（接線，MVP 必要）**：依賴 US1＋US2 的工具實作（T015、T016、T020）；T021、T022 可在 T023～T025 前先寫（先紅後綠）。
- **US3（Phase 6）**：依賴 Phase 2；其 `confirm_summary` 掛載仰賴 Phase 5 已掛入 7 個 schema（T008 已含），故不需再改接線。**測試依賴**：T028 需斷言摘要出現在 `get_external_content`，故需 T014（寫入內容）與 T019、T020（取全文）。
- **US4（Phase 7）**：依賴 US1（重複偵測基礎）；與 US3 獨立。
- **US5（Phase 8）**：依賴 Phase 2；`delete_content` 也已含在 T008 schema 與 T023 接線內。**測試依賴**：T035 需建立測試內容（T014）並斷言刪除後 `search`／`get` 查不到（T019、T020）。
- **Polish（Phase 9）**：T037、T038 可在工具名稱確定後（T008 之後）任何時間做；T039～T045 依賴全部實作；T043 需 PO 檔案；T045 需 PO 同意。

### 使用者故事相依

- US1：Phase 2 後即可，不依賴其他故事。
- US2：Phase 2 後即可（測試資料可由 store 直接寫入）。
- US3、US5：實作獨立於 US1／US2；**測試依賴** T014（寫入）與 T019、T020（查詢）。
- US4：延伸 US1 的匯入流程。

### 同一故事內順序

測試先於實作（先紅後綠）；store → inbox／metadata → tools。

### Parallel Opportunities

- T004／T005、T003 可平行。
- US1 內：T009、T010、T011 三個測試檔可平行；T013 與 T012 可平行。
- US2 內：T017、T018 可平行。
- Phase 5：T021、T022 可平行。
- US3 與 US5 的 **store 層**測試（T027、T035 的 store 部分）可平行；T028、T031、T035 都改 `test_external_content_tools.py`，**同檔須循序**，不可平行。
- T037、T038 可平行。

#### Parallel Example: User Story 1

```text
Task: "撰寫 test_external_content_inbox.py"        (T009)
Task: "撰寫 test_external_content_metadata.py"     (T010)
Task: "撰寫 test_external_content_tools.py US1 部分" (T011)
Task: "建立 external_content_metadata.py"          (T013)  # 與 T012 不同檔案
```

---

## Implementation Strategy

### MVP First（US1＋US2＋Phase 5）

1. 完成 Phase 1（含 PO 同意的 rebase）與 Phase 2。
2. 完成 US1（匯入）→ 在模組層驗證。
3. 完成 US2（查詢）→ 在模組層驗證。
4. 完成 Phase 5（接線＋守門）→ 本機 Claude Code 重啟 MCP 後即可使用；**要讓 claude.ai 使用，另需 T037／T038（專案指示）與 T045（部署並重啟服務）**。
5. T040（磁碟基準）、T042（獨立驗收）、T043（EP466 端到端）通過後，才考慮部署。

### 增量交付

- MVP 後依序加入 US3（摘要確認）、US4（重複與取代）、US5（刪除），每個故事完成即跑該故事的獨立測試與全套守門測試。
- 每個階段完成都先 commit（本分支）；部署（T045）須 PO 當場同意。

### 注意事項

- 驗證不自驗：T042 必須由 fresh agent 執行。
- 任一任務若發現規格或契約與實際程式衝突，先停下回報，不要默默改規格。
- 本功能所有測試與實驗**絕不指向 `poc/data/`**；真實驗證用 `ALPHAVIBE_DATA_DIR=<獨立測試庫>`。
- T001、T043、T045 需要 PO 的同意或素材，其餘任務可由實作者獨立完成。
