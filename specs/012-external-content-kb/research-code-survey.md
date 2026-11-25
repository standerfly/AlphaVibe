# 012 程式碼調查筆記（唯讀）

來源：/Users/stander/My_project/AlphaVibe-prod，commit `a4bccce`（Merge PR #65，function/alphavibe 已部署版）。調查日 2026-11-25。以下路徑皆相對該 worktree。

## 1. article_store.py（1194 行）
- 庫檔：`DB_FILENAME="articles.db"`（article_store.py:30 附近常數區），`os.path.join(abspath(data_dir), DB_FILENAME)`（:276）。data_dir 由呼叫端傳入；server.py:886-888 `_default_data_dir()` = `ALPHAVIBE_DATA_DIR` 或 `<poc/kb-mcp>/../data`。HTTP 路徑由 `app/deps.py:52-` `_resolve_data_dir()`（必須設環境變數、指向正式目錄需 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE=1`）。
- 建表：`ArticleStore.__init__`（:273-283）`makedirs`→`connect(check_same_thread=False)`→`executescript(SCHEMA)`（`CREATE TABLE IF NOT EXISTS`，SCHEMA 起於 :55）→`_ensure_columns()`→commit；刻意不寫任何資料列（docstring :4-6）。
- 遷移：無 user_version；`_ensure_columns`（:285-309）用 `PRAGMA table_info` 檢查欄位、缺則 `ALTER TABLE ADD COLUMN`。
- 唯讀開庫：`open_readonly(cls, data_dir)`（:473-488）。庫檔不存在 → `FileNotFoundError("文章庫尚未建立…")`，不建庫；用 `file:<path>?mode=ro` URI（`?`、`#` 跳脫）；不跑 SCHEMA。
- 搜尋：`search_articles`（:504-567）LIKE（非 FTS5）；`_like_pattern`（:490-493）先跳脫 `\`、`%`、`_` 並加 `ESCAPE '\'`；空白切詞 AND；`limit` 預設 10、上限 30（`DEFAULT_SEARCH_LIMIT`/`MAX_SEARCH_LIMIT`，:35-36 附近），`max(1,min(limit,30))`；僅 status='fetched'；日期新到舊；片段 `_snippet`（:495-502）半徑 60 字、前後加「…」、換行換空白。
- 交易：寫入方法每個自行 `commit()`（如 mark_fetched :354-369）；批次用 `_begin_immediate()`（:314-317，`BEGIN IMMEDIATE`）+ try/commit/except rollback/raise（例 apply_verification_batch :632-652，稽核列與資料同一交易）。
- 其他設計約束可比照：只增不刪（無 delete 方法）、`__init__` 無寫入副作用、`mark_fetched` 內文過短拒寫（:354-365）。

## 2. article_tools.py（250 行）
- schema：`ARTICLE_TOOL_SCHEMAS`（:209-241，list of {name,description,inputSchema}）、`ARTICLE_TOOL_NAMES`（:242）。
- 分派：`call_article_tool(data_dir,name,args)`（:245-250）→`run_search_articles`/`run_get_article`（:187-206，開 `_read_only_store`→查→finally close；缺參數 raise ValueError）。
- 格式化：`format_search_results`（:131-139）、`format_article`（:142-176）回**純文字字串**（非 JSON 物件）；警告字樣只在輸出層加（:7、:13-23）。
- 共用：server.py:29 `import article_tools`、:883 `] + article_tools.ARTICLE_TOOL_SCHEMAS`、:917-920 call_tool 開頭 `if name in ARTICLE_TOOL_NAMES`；us_stock_mcp_server.py:56、:208、:229-231 同樣模式。
- 重要：**010 沒有任何 MCP 寫入工具**（test_article_connectors_parity.py:55-61 守門「文章工具只有 get_article/search_articles」）。寫入走 CLI 腳本（article_manual_transcribe.py 等，呼叫 store.apply_*_batch）。012 若要新增 MCP 寫入工具是新模式。

## 3. server.py／server_readonly.py／us_stock_mcp_server.py
- server.py：`TOOLS` 起於 :35，實測 `len(server.TOOLS)==50`（python 匯入驗證）。寫入工具無獨立標註欄位，只靠「是否在 READONLY_TOOLS」區分。`Server.__init__`（:~907）建 `KBStore(data_dir)`；`handle`（:1317-1372）處理 initialize/ping/tools/list/tools/call；失敗時 `store.conn.rollback()` 並回 `isError:True`、文字「工具執行失敗：…」。`call_tool` 為長 if 鏈（:917 起）。
- server_readonly.py：`READONLY_TOOLS` set（:23-41，實測 31 個）；`READONLY_TOOL_SCHEMAS`（:43）過濾 kb_server.TOOLS；`ReadonlyServer.handle`（:46-59）tools/list 只回白名單、tools/call 非白名單回 isError「這個唯讀 wrapper 沒有授權呼叫寫入工具」。docstring 內「50 個」「31 個」字樣（:6、:9）為註解，改工具數時順手更新。stock-researcher agent 白名單在 ~/.claude，不在 repo。
- us_stock_mcp_server.py：`TOOLS` 起於 :65，8 個美股工具（:67 parse_and_save_us_trade、:90、:100、:109、:121、:152、:171、:193）+ `article_tools.ARTICLE_TOOL_SCHEMAS`（:208）= 10；call_tool :229-231 先攔截文章工具；完全不 import kb_store（docstring :6-8）。
- 新增 012 工具的註冊點：server.py TOOLS（+ call_tool 分派）、server_readonly.py READONLY_TOOLS（僅查詢工具）、us_stock_mcp_server.py TOOLS（查詢工具若要美股也有）。可比照 010 把 012 工具組做成獨立 `xxx_tools.py` 模組以兩端共用。

## 4. app/routers/mcp.py（179 行）
- 路由：`POST /mcp`（:71）、`POST /mcp/{token}`（:92，server_module=`mcp_http_gateway.kb_server`，data_dir=`_resolve_data_dir`）、`POST /mcp/us/{token}`（:117，server_module=`us_stock_mcp_server`，`_resolve_us_stock_data_dir`），皆經 `_path_token_post`（:140-165）→ `run_in_threadpool(mcp_http_gateway.handle_mcp_post, ...)`。GET 兩路徑回 405（:168-179）。
- 分派：`handle_mcp_post`（poc/kb-mcp/mcp_http_gateway.py:149-）每請求 `server_module.Server(data_dir=...)`（:208）、handle、finally `store.close()`；例外回 500 JSON-RPC -32603；notification 回 202。
- 密鑰：`path_token_matches(token)`（gateway :113，compare_digest；錯誤/未設定回通用 404，mcp.py:153-158）；先驗再讀 body（:145、:159）；`/mcp` 另有 `mcp_auth_ok()` fail-closed 503（mcp.py:79-85）。Basic Auth 白名單 app/deps `_is_mcp_path()`。
- 請求大小限制／逾時：app 層**未查到**（搜尋 mcp.py、mcp_http_gateway.py 的 MAX/timeout/Content-Length；僅舊 stdlib `MCPHandler` :263 讀 Content-Length 無上限）。FastAPI/uvicorn 無應用層 body 上限；ngrok／claude.ai 端限制未查證。重要含意：大內文寫入工具沒有程式碼層面的 size guard，012 需自行在工具內限制長度。
- 注意：同一個 Server 於每個 HTTP 請求新建（含 KBStore 建構），012 的 store 開關要輕量。

## 5. 守門測試（皆在 poc/kb-mcp/tests/）
- test_pnl.py:244-251 `test_tool_counts`：`assertEqual(len(server.TOOLS), 50)`（:249）、`len(READONLY_TOOLS), 31`（:250）；docstring :245-247 追加歷史說明。
- test_traceability.py:261-262：`names=[t["name"] for t in server.TOOLS]`、`assertEqual(len(names), 50)`；docstring 約 :256-259 追加歷史。
- test_us_stock_mcp_server.py:18-29 `test_ten_tools_registered`：以**名稱集合**相等（非數字）；美股若加工具要補進集合，方法名也含 "ten"。
- test_article_connectors_parity.py:55-61：只允許名稱含 "article" 的工具為 get_article/search_articles——若 012 工具名含 "article" 會撞到，命名請避開或同步改此測試；:61 斷言文章工具在 READONLY_TOOLS。
- test_article_verification.py:297-300：`names with "verif"/"reviewed"` 必須為空；美股含 "article" 的工具數 ==2。012 工具名避免含 verif/reviewed/article。
- test_claude_ai_connector.py:40-47（us module 工具集合與 TOOLS 相等，無硬數字）；:157 檢查某工具在白名單。
- 新增 N 個工具（其中 M 個唯讀）：test_pnl.py:249-250 與 test_traceability.py:262 的數字（50→50+N、31→31+M）；若美股也掛則 test_us_stock_mcp_server.py:20-29 集合。另 server_readonly.py:6、:9 註解數字（非測試）。

## 6. 稽核寫法
- 可重用：`article_store.alert_log(kind,key,day)` 表（:122-127，PRIMARY KEY 三欄；`alert_once` :1188-1193 用 `INSERT OR IGNORE`），批次寫入方法有 `audit_kind/audit_key/audit_day` 參數，與資料同交易寫入（:632-652），key 只存數量與 method。限制：以 (kind,key,day) 去重，不是逐筆事件流水（同日同 key 只留一筆），粒度為「日」。另有 `import_runs`／`pipeline_run` 表記錄執行（:107、:148）。
- 另一種：gateway `audit_log.jsonl`（app/routers/gateway_monitor.py:76、:407-421 `_append_audit_log`，JSONL 追加，timestamp/channel/domain/action/text≤2000），檔案在 gateway state 目錄、非 DB，且屬 gateway 領域，不建議直接掛用。
- 若 012 需要「何時／哪一筆」：建議在 012 自己的庫新增專屬 audit 表，沿用「與資料同交易」寫法。（這是推論。）

## 7. URL／連結正規化
- function/alphavibe：`poc/kb-mcp/order_ref.py:21` `normalize_order_ref(ref)`（委託書號，與 URL 無關，不可重用）。
- `article_reconcile.py:59` `_norm_url`（小寫、去 `://www.`、去尾斜線）只存在於 011-substack-fetch-store 分支（git show 驗證），**不在 function/alphavibe**；且為私有函式、規則過簡，不處理 youtu.be／watch?v=／追蹤參數。
- substack `link_norm` 僅見於 011 分支的 specs 文件（specs/011-substack-fetch-store/data-model.md:36、research R6 規則），**011 分支只有規格、無程式碼**（git grep 無任何 .py 命中），所以沒有可重用實作。
- YouTube 相關：prod 中 `server.py`、`tests/test_kb.py` 有 "youtube" 字樣（未深查，推測為 note／來源文字），非辨識函式。結論：YouTube 身分判斷須自寫。

## 8. 本機 Claude Code MCP 設定
- `/Users/stander/My_project/AlphaVibe-prod/.mcp.json`（專案層，無 token）：`alphavibe-kb` → `python3 poc/kb-mcp/server.py`（stdio，台股，完整 50 工具含寫入）；`alphavibe-us-stock` → `python3 poc/kb-mcp/us_stock_mcp_server.py`。是的，指向 poc/kb-mcp/server.py。資料目錄走 server.py 預設 `<kb-mcp>/../data`（即該 worktree 的 poc/data），或環境變數 `ALPHAVIBE_DATA_DIR`。
- Cline 走 `server_readonly.py`（見 server_readonly.py docstring；實際 cline_mcp_settings.json 未讀取）。
- claude.ai 連接器走 HTTP 路由（第 4 節），非 stdio。
- 本次未讀取 ~/.claude 內任何檔案，未輸出任何 token。

## 未查到
- app 層 request size／timeout 設定；ngrok／claude.ai 端上限。
- 實際 launchd plist 的 ALPHAVIBE_DATA_DIR 值（未讀 ~/Library）。
