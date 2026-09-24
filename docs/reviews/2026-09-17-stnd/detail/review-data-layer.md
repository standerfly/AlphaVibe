# AlphaVibe 資料層審查報告（2026-09-17，唯讀審查）

審查範圍：`poc/kb-mcp/kb_store.py`（2121行）、`us_stock_store.py`（524行）、
SQLite schema（`poc/data/alphavibe.db`／`us_stocks.db`，唯讀 `sqlite3 .schema`／
`PRAGMA` 查詢）、`holdings_sync.py`、`trade_ledger_parser.py`、`pnl.py`、
`holdings_parser.py`、`trade_text_parser.py`、`stock_alias_resolver.py`、
三支 backfill 腳本、`seed_assets_once.py`、`server.py`／`us_stock_mcp_server.py`
（stdio MCP 常駐服務）、`report_server.py`／`app/deps.py`（HTTP 連線生命週期）、
`mcp_http_gateway.py`、launchd plists、`.mcp.json`。全程唯讀，未修改／寫入
任何檔案或資料庫。

---

## 結論總覽

**PASS（發現 9 個問題：必修 1／該修 4／可不修 4）**

---

## 必修（會弄壞或弄錯資料）

### F1. stdio MCP 常駐服務缺少 rollback，`save_holdings()` 的例外會讓半套資料被下一次無關的寫入偷偷 commit 掉

- **位置**：`poc/kb-mcp/kb_store.py:702-748`（`save_holdings`）＋
  `poc/kb-mcp/server.py:1270-1301`（`handle()` 的 `tools/call` 分派，
  except 在 1299 行）＋ `poc/kb-mcp/us_stock_mcp_server.py`（同構，except 在 314 行）。
- **為什麼是問題**：`.mcp.json`（repo 根目錄）把 `alphavibe-kb`／
  `alphavibe-us-stock` 設定成 **stdio 常駐子行程**（`python3 poc/kb-mcp/server.py`），
  `Server.__init__`（`server.py:889`）只建立**一個** `KBStore`／SQLite 連線，
  整個對話 session 期間所有工具呼叫共用同一條連線、同一個未提交的
  transaction 狀態（Python sqlite3 模組預設 `isolation_level=""`，多次
  `execute()` 之間不會自動 commit）。`save_holdings()` 對 `rows` 逐筆
  迴圈：若某一筆缺 `code` 會在**迴圈中途** `raise ValueError`（第 725 行），
  但前面已對其他合法列呼叫過 `self.conn.execute("INSERT INTO holdings...")`
  （第 738 行）尚未 `commit()`。這個例外被 `handle()` 的
  `except Exception as exc:`（server.py:1299）接住、回傳 `isError:true`
  給呼叫端，**但完全沒有呼叫 `rollback()`**——連線上遺留的那些已
  `execute()` 但未 commit 的 INSERT 會一直留在這個常駐連線的 transaction
  裡，直到同一個 session 裡**任何一次不相關的成功寫入**（例如接著呼叫
  `save_stance`）觸發它自己的 `self.conn.commit()`，把前面遺留的
  holdings INSERT 也一併悄悄提交進正式資料庫。
- **具體失敗情境**：`save_holdings` 的工具描述明講是「將截圖解析出的
  持股寫入」（server.py:254），這種輸入天生容易漏欄位。MCP 工具的
  `inputSchema` 雖然宣告 `items.required=["code"]`（server.py:270），但
  `call_tool()`（server.py:998-1001）直接把 `args["rows"]` 原樣丟給
  `store.save_holdings()`，**沒有任何 JSON Schema 執行期驗證**，
  schema 只是給 LLM 看的說明文字。情境：Claude 在一次 session 呼叫
  `save_holdings(rows=[{"code":"2330","shares":100,"avg_cost":900}, {"shares":50}])`
  （第二筆漏了 code，例如截圖 OCR 漏抓）→ 工具回報失敗，使用者/Claude
  以為整批沒寫入 → 但 2330 那筆其實已經 `execute()` 過。稍後同一個對話
  session 呼叫任何其他成功的寫入工具（`save_stance`／`save_comment`／
  `save_trade_ledger_entry` 皆可）→ 2330 那筆持股被夾帶寫入
  `holdings` 表，且因為 `get_holdings()` 取每天每代碼最大 id 那列
  （kb_store.py:775），這筆「使用者以為被拒絕」的資料可能直接變成
  最新持股快照，汙染 `pnl.py` 的 FIFO 計算與各處持股顯示，**沒有任何
  錯誤訊息或警示**。
- **影響範圍確認**：HTTP 路徑（`report_server.py`／FastAPI `app/deps.py`）
  不受影響——兩者都是每個 request 建立新 `KBStore`、`finally: store.close()`
  收尾，`sqlite3.Connection.close()` 對未 commit 的 transaction 會自動
  rollback（已用 `grep`／程式碼確認 report_server.py 18 處 `store =
  KBStore` 對 18 處 `store.close()`，皆在 try/finally 內）。`mcp_http_gateway.py:189-197`
  的 `/mcp` HTTP 路徑也是**每個 request 現開現關**（`server_instance =
  kb_server.Server(...)`、`finally: server_instance.store.close()`），
  同樣不受影響。**只有 `.mcp.json` 設定的兩個 stdio 常駐服務**（本機
  Claude Code／Claude Desktop 直接呼叫的那條路徑，也就是這次對話裡
  `mcp__alphavibe-kb__*`／`mcp__alphavibe-us-stock__*` 這組工具背後的
  實際實作）會踩到。
- **掃描確認**：對 `kb_store.py` 全部方法做「迴圈內有 `self.conn.execute`
  且迴圈內有 `raise`、且方法內只有結尾一個 `commit()`」的靜態掃描，
  唯一命中的是 `save_holdings`（另一個候選 `save_exit_threshold` 誤判，
  它的迴圈只做參數驗證、沒有任何 DB 寫入，所有 `raise` 都在第一次
  `execute()` 之前，安全）。`us_stock_store.py` 同樣掃描**無命中**——
  該檔案所有寫入方法都是單一 `execute()`+`commit()`，沒有這個模式。
- **修法建議**：在 `server.py:1299` 與 `us_stock_mcp_server.py:314` 的
  `except Exception as exc:` 區塊內，回傳錯誤之前加一行
  `self.store.conn.rollback()`（沒有待處理的 transaction 時這是
  no-op，不會有副作用）。這是伺服器層級的一次性修法，不需要逐一修改
  每個 store 方法。若要更保險，`save_holdings()` 本身也可以改成先
  完整驗證整批 `rows` 都有 `code` 再開始寫入（兩者互不排斥）。
- **工作量**：小（兩個檔案各加一行，屬於防禦性修正，風險低）。

---

## 該修（維護成本／健壯性缺口）

### F2. 兩個資料庫都沒有開 WAL 模式、也沒有設定 busy_timeout

- **位置**：`kb_store.py:386`（`KBStore.__init__`）、
  `us_stock_store.py:138`（`USStockStore.__init__`）。
- **驗證**：`sqlite3 poc/data/alphavibe.db "PRAGMA journal_mode;"` 與
  同一指令對 `us_stocks.db` 皆回傳 `delete`（預設 rollback journal），
  不是 `wal`；程式碼中對兩個檔案 grep `journal_mode|busy_timeout|PRAGMA`
  除了 `_migrate()` 內部的 `PRAGMA table_info` 之外沒有其他 PRAGMA。
- **為什麼是問題**：這個系統有多個會同時碰同一個 SQLite 檔案的行程——
  `report_server.py`（`ThreadingHTTPServer`，多執行緒）、FastAPI app、
  `mcp_http_gateway.py`（Telegram 管家）、`.mcp.json` 的 stdio 常駐
  服務、以及三個 launchd 排程（`com.alphavibe.marketscan.plist`／
  `com.alphavibe.moduled.plist`／`com.alphavibe.usstockscan.plist`）。
  沒有 WAL 時，讀者與寫者會互相鎖住整個資料庫檔案；Python
  `sqlite3.connect()` 預設有 5 秒的重試 timeout，短暫的寫入衝突通常
  撐得過去，但排程批次寫入（如 `market_scan.py` 一次寫入數百列
  `market_scan_results`）若與互動使用或另一個排程重疊，仍有機會超過
  5 秒觸發 `sqlite3.OperationalError: database is locked`。
- **具體失敗情境**：**未在任何 log 檔案中找到過去實際發生「database is
  locked」的證據**（本機找不到 AlphaVibe 相關 log 檔）——這是預防性
  發現，不是已發生的事故，如實標註「未驗證是否已發生過」。
- **修法建議**：在兩個 `__init__` 裡 `executescript(SCHEMA)` 之前加
  `self.conn.execute("PRAGMA journal_mode=WAL")` 與
  `self.conn.execute("PRAGMA busy_timeout=10000")`（或視情況調整秒數）。
- **工作量**：小（兩處各加兩行 PRAGMA；WAL 模式會在資料目錄多出
  `-wal`／`-shm` 檔，需確認備份腳本〔見 F4〕與部署流程知道要一併處理）。

### F3. `save_trade_ledger_entry` 沒有 shares／price 正數驗證，且是可被 Claude 直接呼叫的寫入工具

- **位置**：`kb_store.py:1175-1193`（`save_trade_ledger_entry`）、
  `server.py:420-439`（MCP 工具 schema）、`server.py:1036-1041`（呼叫點）。
- **對照**：`us_stock_store.py:150-166`（`save_trade`）對同類欄位有
  `if shares is None or shares <= 0: raise ValueError`／
  `if price is None or price <= 0: raise ValueError`；`save_exit_threshold`
  （kb_store.py:1211-1247）也驗證 `number <= 0` 才 raise。唯獨
  `save_trade_ledger_entry` 只驗證 `code`／`action`／`date` 非空，
  完全沒檢查 `shares`／`price` 的數值合理性。
- **為什麼是問題**：`trade_ledger` 是 PO 自己的交易流水，餵給
  `pnl.py` 的 FIFO 損益計算與 `holdings_sync.py` 的持股自動同步
  （交易匯入後自動觸發，見 `trade_ledger_parser.py:427-430`）。這個
  MCP 工具是**直接暴露給 Claude 呼叫**的寫入工具（不像
  `parse_and_save_trade_ledger` 是走正則解析、數值來源是固定格式的
  regex，不可能產生負數/零），若 Claude 在對話中誤判或誤填（例如
  聽錯使用者口述的股數）呼叫 `save_trade_ledger_entry(shares=0, ...)`
  或 `price=-10`，會被原樣寫入 `trade_ledger`，接著自動觸發
  `sync_holdings_from_trades()` 用這個異常值重算加權平均成本
  （`holdings_sync.py:112-141` 的算式對 0 或負數股數沒有防呆），
  可能靜默把某檔持股的均價算壞。
- **修法建議**：在 `save_trade_ledger_entry` 開頭加
  `if shares is None or shares <= 0: raise ValueError(...)` 與
  `if price is None or price <= 0: raise ValueError(...)`，比照
  `us_stock_store.save_trade` 的既有寫法。
- **工作量**：小（4 行驗證邏輯；需確認既有測試/既有資料沒有依賴
  0 或負數的邊界輸入——已用 `grep` 快速檢查 `save_trade_ledger_entry`
  呼叫點只有 `resolve_and_save_trade_ledger` 一處，該處數值恆正，
  改動風險低）。

### F4. 正式資料庫沒有任何自動化備份機制

- **驗證**：`~/Library/LaunchAgents/` 下 6 個 `com.alphavibe.*.plist`
  （devtunnel／marketscan／moduled／ngrok／reportserver／usstockscan）
  皆未包含備份相關指令；`crontab -l` 為空；repo 內所有 `.py` 檔案
  grep `backup`／`.bak` 只命中 `report_server.py`／`mcp_http_gateway.py`
  的既有防重複邏輯字面比對（跟資料庫備份無關）。
- **現況**：`poc/data/` 下有 5 個手動備份檔（`alphavibe.db.bak-*`，
  最新 2026-07-31，皆為「動手術前」的一次性快照，命名可見
  `pre-phase2`／`before-holdings-tradeledger-reset` 等字樣）；
  `~/.claude/backups/` 下另有 2 份更新的（2026-09-02），同樣是手動
  觸發、非排程。**距今（2026-09-17）最新的備份已超過兩週**，且沒有
  任何機制保證下一次「動手術前」會記得手動備份。
- **為什麼是問題**：正式庫是使用者真實持股與交易紀錄的唯一存放處，
  沒有排程備份代表：磁碟損毀、誤執行的遷移腳本、或本報告 F1
  這類半套寫入，一旦真的造成資料損壞，能復原到的最近時間點可能是
  兩週以上之前，且完全依賴「剛好上次有手動備份」的運氣。
- **修法建議**：新增一個 launchd 排程（比照既有 `com.alphavibe.marketscan.plist`
  的每日排程模式），每天把 `poc/data/alphavibe.db`、`poc/data/us_stocks.db`
  （若已切到 WAL 模式，見 F2，需一併處理 `-wal`/`-shm` 或先
  `PRAGMA wal_checkpoint`）複製到帶日期戳記的備份路徑，並訂一個
  保留策略（例如只留最近 14 天＋每月一份）；理想上備份地點不要
  跟正式庫同一顆磁碟（例如另一個磁區或雲端同步資料夾）。
- **工作量**：中（新增 plist＋簡單 shell/python 腳本＋決定保留策略與
  異地備援方式，屬於一次性基礎設施工作，非程式邏輯改動）。

### F5. `us_stock_store.py` 沒有對應 `kb_store.py._migrate()` 的欄位遷移機制

- **位置**：`us_stock_store.py` 全檔案（無 `_MIGRATIONS`／`_migrate()`
  等價物），對照 `kb_store.py:308-357`（`_MIGRATIONS` 資料表）與
  `kb_store.py:483-496`（`_migrate()`，用 `PRAGMA table_info` 逐一補
  缺欄位，冪等、不清空舊資料）。
- **為什麼是問題**：目前 `us_stocks.db` 四張表自建立以來沒有新增過
  欄位，所以還沒踩到這個缺口；但美股系統仍在擴充中（模組
  docstring 標記 Phase 5／T026 等仍在進行的工作），下一次真的需要
  對既有表補欄位時，`CREATE TABLE IF NOT EXISTS` 對已存在的表**不會**
  自動補新欄位（這正是 `kb_store.py._migrate()` 存在的原因），屆時
  沒有現成機制可用，得在時間壓力下重新發明一次 kb_store.py 已經
  驗證過的做法。
- **修法建議**：現在就比照 `kb_store.py` 補一份輕量的 `_MIGRATIONS`
  字典＋`_migrate()` 方法到 `USStockStore.__init__`（可以先是空字典，
  之後新增欄位時往裡面加即可），成本低、可預先鋪好路。
- **工作量**：小（複製 `kb_store.py` 現成的 `_migrate()` 邏輯，改成
  作用在 `us_stocks.db` 的四張表）。

---

## 可不修（已知取捨或影響極小，記錄供未來參考）

### N1. `backfill_holdings_sync_once.py` 明確不是冪等的

- **位置**：`poc/kb-mcp/backfill_holdings_sync_once.py:22-27`（docstring
  已用整段文字警告「重跑會讓交易被套用兩次」）。
- **評估**：這是一次性、需要人手動執行的維護腳本，且風險已經在
  docstring 裡講得很清楚（比其他同類腳本更詳細），程式碼本身沒有
  基於「這批交易是否已同步過」的判斷式防呆。因為這支腳本已完成
  它 2026-09-02 當時的歷史任務（見 kb_store.py 相關教訓紀錄），
  之後大機率不會再被呼叫；若未來真的要再次回溯同步，建議屆時補
  一個「檢查 holdings 快照是否已反映這批交易」的判斷再執行，
  現在不修不影響現況正確性。

### N2. `asset_holdings`／`asset_buildup_plans`／`asset_contribution_events` 的 `REFERENCES` 外鍵宣告未被強制

- **驗證**：`grep -rn "foreign_keys" poc/kb-mcp/*.py app/*.py` 全部檔案
  **零命中**——沒有任何地方執行過 `PRAGMA foreign_keys=ON`，SQLite
  預設不強制外鍵，因此 schema 裡的 `REFERENCES asset_pockets(id)`
  等寫法純粹是文件用途，資料庫層面不會擋下指向不存在 id 的寫入。
- **評估**：目前沒有任何刪除 `asset_pockets`／`asset_accounts` 列的
  方法（只有 `archive_asset_pocket`／`archive_asset_account`，軟刪除），
  所以目前不存在會產生孤兒列的路徑，風險是理論性的。若未來新增
  「真的刪除口袋/帳戶」的功能，屆時要記得補 `PRAGMA foreign_keys=ON`
  或在應用層驗證，現在不修。

### N3. `save_holdings` 的同日重複防呆是 check-then-insert，非原子操作

- **位置**：`kb_store.py:723-733`。
- **評估**：兩個不同連線（例如 Telegram 管家自動同步＋使用者手動
  在網頁確認）幾乎同時對同一個 `(code, snapshot_date)` 呼叫
  `save_holdings`，理論上都可能在對方 commit 前通過「不是重複」的
  檢查，各自插入一列。但因為這個防呆本身只在兩筆數值**完全相同**時
  才判定為重複，即使真的競態出現兩列，`get_holdings()` 一律取
  `max(id)` 那列（kb_store.py:775-782），而兩列數值相同，顯示結果
  仍然正確——只會多一筆無害的重複歷史列，不會顯示錯誤數字。
  單一使用者、低頻寫入的場景下發生機率也極低，現在不修。

### N4. `stock_alias_resolver.py` 的名稱正規化若撞名，靜默取「FinMind清單裡先出現」的那個

- **位置**：`stock_alias_resolver.py:62-68`（`finmind_lookup` 建表用
  `if norm and norm not in finmind_lookup` 先到先贏，無碰撞警告）。
- **評估**：只有在兩檔不同的真實股票，去除連字號/空白後正規化成
  完全相同字串時才會誤判，目前沒有證據顯示台股清單裡存在這種
  撞名（未實際窮舉驗證，如實標註「未驗證」）。一旦命中的名稱會被
  快取進 `stock_aliases`（`INSERT OR REPLACE`，以 `name` 為主鍵），
  之後同名的交易會一路沿用錯的代碼，影響不小，但觸發機率評估極低，
  現在不修，建議之後若真的新增撞名的個股再處理。

---

## 各審查角度檢查方式與結論摘要

1. **建構即副作用**：對 `kb_store.py`／`us_stock_store.py`／
   `holdings_sync.py`／`trade_ledger_parser.py`／`trade_text_parser.py`／
   `holdings_parser.py`／`pnl.py`／`stock_alias_resolver.py` 做 AST
   掃描（找模組頂層的函式呼叫），**零命中**——沒有新的「import 或
   建構就觸發寫入/外部呼叫」殘留。`KBStore.__init__`／
   `USStockStore.__init__` 都已確認只做 schema 建立與遷移，資產種子
   資料已正確移出建構子（2026-08-22 修法仍然有效，未發現回歸）。
   `_migrate()`／`executescript(SCHEMA)` 本身在每次建構時都會執行
   （`CREATE TABLE IF NOT EXISTS`／逐欄位 `ALTER TABLE`），這是冪等的
   schema 操作，不寫入使用者資料，不計入本類問題。

2. **併發與連線管理**：發現 F1（必修）、F2（該修）、N3（可不修）。
   額外確認：`report_server.py` 18 處 `store = KBStore(...)` 全部對應
   18 處 `store.close()`，皆在 try/finally 內，無連線洩漏；
   `app/deps.py::get_kb_store()` 用 FastAPI yield-dependency 同樣模式，
   `finally: store.close()`。多步驟寫入的 transaction 邊界另外檢查了
   `upsert_asset_holding`／`complete_asset_buildup_month`／
   `undo_asset_buildup_month`／`record_asset_contribution`／
   `delete_asset_contribution`（kb_store.py:1677-2109）：全部把多個
   `execute()` 群組在單一 `commit()` 之前、且方法內沒有會在寫入
   之間拋出例外的驗證邏輯（所有 `raise ValueError` 都在第一個
   `execute()` 之前），在目前的呼叫模式下不會產生半套資料——這組
   方法是本次審查中設計得最嚴謹的一塊。

3. **Schema 設計**：以唯讀 `sqlite3 .schema` 完整列出兩個正式庫的
   全部表。發現 N2（外鍵未強制）；`holdings` 表沒有 `(code,
   snapshot_date)` 唯一約束是刻意設計（靠 `id` 遞增＋
   `get_holdings()` 取 max(id) 決勝負，docstring 說明完整，已在
   N3 一併評估其競態風險）。日期/金額欄位命名：`stances.date`／
   `snapshots.snapshot_date`／`holdings.snapshot_date`／
   `trade_ledger.date`／`us_trades.trade_date`／
   `asset_contribution_events.event_date` 對「一個日期」這個概念
   用了 4 種不同欄位名（`date`／`*_date` 前綴不一致），純屬命名
   風格不統一，不影響正確性，判定可不修、不單獨列入編號清單。
   金額/回檔率等數值統一用 REAL 存小數（如 0.095=9.5%），
   `kb_store.py` 開頭有明確註解統一單位慣例，未發現不一致。

4. **資料遷移與版本**：`kb_store._migrate()`（483-496行）資料驅動、
   冪等，逐欄位檢查存在與否才 ALTER TABLE，設計良好；發現 F5
   （`us_stock_store.py` 缺對應機制）。三支 backfill 腳本：
   `backfill_price_history_once.py` 冪等（PK 是 `(code,date)`，
   `INSERT OR REPLACE` 語意，docstring 明講冪等）；
   `seed_assets_once.py` 冪等（寫入前用 `COUNT(*)` 判斷是否已有資料，
   腳本與 `KBStore.seed_asset_defaults()` 兩層都做了這個檢查）；
   `backfill_holdings_sync_once.py` 非冪等，見 N1。三支腳本都要求
   `--data-dir` 必填、無預設值，一致遵循 2026-08-22 教訓的防呆模式。

5. **資料寫入的正確性**：完整讀過 `trade_ledger_parser.py`（439行）、
   `holdings_sync.py`（154行）、`pnl.py`（185行）、
   `holdings_parser.py`（88行）、`trade_text_parser.py` 前120行。
   發現 F3。邊界情況逐項確認：零股／張股轉換（`trade_text_parser.py`
   的「股」不乘1000、「張」乘1000，`pnl.py` docstring 有專門一段
   說明這是曾經真實踩過的坑）；賣超（`holdings_sync.py` 用
   `max(0, shares-sell)` 防止負數並記錄 `oversold_codes`；`pnl.py`
   用 `status="history_incomplete"` 標記、不捏造成本）；同日多筆
   （三個解析器都用「(date, 原始出現順序)」穩定排序，不亂猜真實
   下單時間）；重複匯入（`trade_ledger_parser.py` 靠 `order_ref`
   查重，docstring 明確承認「沒有 order_ref 的交易完全不做防重複
   檢查」是刻意的取捨——PO 已裁決寧可放行不要誤殺，本審查判定這是
   已知並被明確接受的產品決定，不計入問題清單，但在此如實記錄該
   殘餘風險的存在）；解析失敗（三個解析器一致地把「看起來像資料列
   但格式跑掉」的行歸入 `unparsed_lines`／`unresolved_names`，
   從不靜默丟棄——已逐一確認程式碼行為，不是只看 docstring 宣稱）。

6. **備份與可回復性**：發現 F4。已查 `~/Library/LaunchAgents/` 全部
   6 個 AlphaVibe 相關 plist 內容、`crontab -l`（空）、repo 內
   `backup`/`.bak` 關鍵字全文，確認沒有任何自動化排程。

---

## 使用過的檢查角度／方法清單

- 靜態閱讀：`kb_store.py` 全 2121 行分段讀完（含 SCHEMA 常數、
  `__init__`／`_migrate`／`seed_asset_defaults`／全部 asset_* 方法／
  holdings／trade_ledger／exit_threshold／market_scan 相關方法）
- 靜態閱讀：`us_stock_store.py`、`holdings_sync.py`、`pnl.py`、
  `trade_ledger_parser.py`、`holdings_parser.py`、`trade_text_parser.py`
  （前120行）、`stock_alias_resolver.py` 全文
- 靜態閱讀：三支 backfill 腳本、`seed_assets_once.py` 全文
- 唯讀 SQL 查詢：`sqlite3 poc/data/alphavibe.db ".schema"`、
  `sqlite3 poc/data/us_stocks.db ".schema"`、
  `PRAGMA journal_mode` 對兩個資料庫
- grep／AST 靜態掃描：連線建構呼叫點清單（`grep -rn "sqlite3.connect\|KBStore(\|USStockStore("`）、
  `foreign_keys`／`journal_mode`／`busy_timeout` 關鍵字、
  「迴圈內 execute + raise + 單一 commit」模式掃描（Python AST）、
  模組頂層副作用呼叫掃描（Python AST）
- 連線生命週期交叉核對：`report_server.py` 的 `store =` 與
  `store.close()` 出現次數比對（18 對 18）
- 檔案系統查證：`ls -la poc/data/`（備份檔清單與時間戳）、
  `~/Library/LaunchAgents/` 全部 plist、`crontab -l`
- 外部設定查證：`.mcp.json`（確認 stdio 常駐服務的實際配置）
