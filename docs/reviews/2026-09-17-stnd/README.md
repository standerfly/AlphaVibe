# STND 系統體檢報告（2026-09-17）

> 審查範圍：`app/`(3,735行) + `poc/kb-mcp/`(14,680行) + `web/src/`(5,394行) + 27個測試檔 + 部署運維 + 13個分支
> 方法：四個獨立 agent 分區審查（全程唯讀），主對話交叉比對並實測驗證關鍵宣稱
> 詳細報告：`detail/` 下四份，共 2,007 行

## 一句話結論

**地基是好的，問題集中在四個舊檔案與「沒有安全網」這件事上。**

依賴方向單向乾淨、`app/` 零裸 SQL、資料目錄雙旗標防呆紮實、新模組都小而純——
這些不用花錢。真正該動的必修只有 5 件，其中 3 件加起來不到一天。

---

## 執行進度

| 批次 | 狀態 |
|---|---|
| **第一批：止血**（A2 ＋ A3 ＋ B3） | ✅ **2026-09-17 完成，獨立驗收 9/9 PASS** |
| **第二批：安全網**（A5 ＋ B4） | ✅ **2026-09-17 完成** |
| 第三批：對帳（A1） | 未開始，需 PO 提供試算素材 |
| 第四批：減重（B1 ＋ B2） | 未開始 |
| 隨時可做（A4 ＋ B5） | 未開始，需 PO 決定 |

第一批的產出與驗證證據見下方各節的「已完成」註記。

---

## A. 必修（按「會不會真的咬人」排序）

### A1. 資產情境試算正在給你錯的數字，而你拿它做退休規劃

- 位置：`app/routers/assets.py:290-437`（`_simulate_asset_scenario` 等）
- 事實：程式碼裡的 `_SIMULATE_DISCLAIMER` **自己承認**「公式尚未核對、約 1~2% 誤差」，
  而且這段字串會回傳給前端顯示。全 repo 對這幾個函式與 `/api/assets/simulate`
  的測試覆蓋是 **0**（grep `simulate` 在 `app/tests` 命中 0）。
- 為什麼排第一：這是全系統唯一「輸出錯誤數字給人做重大決策」的問題。
  其他問題頂多是程式壞掉或難維護，這個是**安靜地算錯**。
- 兩個 agent 獨立指出同一件事（後端架構 F3、測試運維 #2）。
- 工作量：**1-3 天**（需要你提供原始試算素材來對帳，這部分我做不了）

### A2. MCP 寫入失敗不會 rollback，髒資料會悄悄進正式庫

- 位置：`poc/kb-mcp/kb_store.py:702-748`(`save_holdings`)、
  `poc/kb-mcp/server.py:1289-1301`、`poc/kb-mcp/us_stock_mcp_server.py:314`
- 機制：常駐的 stdio MCP 服務整個 session 共用一條 SQLite 連線。
  `save_holdings` 逐筆迴圈時若某筆缺 `code` 會 raise，但前面已 `execute()`
  的列沒有 commit 也**沒有 rollback**——它們會被同一 session 裡
  **下一次任何無關的成功寫入**一起 commit 進正式 `holdings` 表。
- 你會看到什麼：以為那批匯入被拒絕了，實際上部分資料進去了，FIFO 損益跟著錯。
- HTTP 路徑（FastAPI）因為每請求開關連線，不受影響。只有 MCP 常駐服務會中。
- 工作量：**小**（兩處各加一行 `rollback()`）

> **✅ 2026-09-17 已完成**。根因修在 `kb_store.py:save_holdings`（整批包 try／失敗
> rollback 後原樣 re-raise，對外行為不變）；`server.py` 與 `us_stock_mcp_server.py`
> 的 `tools/call` except 加 rollback 當防禦網，涵蓋日後新增的寫入方法。
> 新增 4 個回歸測試（`test_kb.py` 的 `HoldingsBatchAtomicityTest` 與
> `McpSessionRollbackE2ETest`，後者用真實 stdio 子行程重現共用連線情境）。
> 驗證：還原修法後那兩個關鍵測試確實 FAIL，放回後全過；全套 869→873 綠。
> 附帶查證：AST 掃描確認同類型風險全庫只有這一處（另外 8 個資產方法的
> `raise` 都在 SELECT 驗證之後，尚未寫入任何東西，不受影響）。

### A3. 正式庫零自動備份

- 已查證：6 個 launchd plist 與 crontab 全部沒有備份邏輯，現存都是手動快照，
  最新一份超過兩週。
- 與 A2 是複合風險：A2 讓資料可能靜默損壞，A3 讓損壞後無法回復。
  單獨看都還好，疊在一起是「發現時已經來不及」。
- 工作量：**小**（一個 launchd + `sqlite3 .backup`，半天內）

> **✅ 2026-09-17 已完成**。`poc/kb-mcp/backup_databases.py`：用 SQLite 線上備份
> API（服務正在寫入也能取得一致快照，不必停機）、備份後 `PRAGMA integrity_check`
> 驗過才算數、gzip 壓縮（7.2MB→2.3MB）、日備留 30 份＋每月 1 號的月備留 24 份。
> 排程 `~/Library/LaunchAgents/com.alphavibe.dbbackup.plist`，每天 03:30（避開
> 02:00 的 market scan），已用 `kickstart` 在真實 launchd 環境驗證可執行。
> 備份位置 `~/AlphaVibe-backups/`。
> 驗證：實際解壓還原，35 張表列數全數一致（holdings 65／trade_ledger 537／
> stances 664）；輪替邏輯造 80 個假檔測過，只刪該刪的，`alphavibe.db`、
> `alphavibe-notes.md` 這類容易誤中的檔名均未被碰。

### A4. 管家分頁已經從正式環境消失了

- 已獨立驗證：`web/dist/` grep「管家/Gateway」**0 命中**；
  目前 `function/alphavibe` 分支的 `web/src/pages/` 裡根本沒有 `Gateway.jsx`。
  它只活在未合併的 `function/stnd-gateway-web`（2 個 commit）。
- 推測時點：2026-09-10 前後在 `function/alphavibe` 上重新 build `web/dist`
  時覆蓋掉的。memory 記載 8/30~31 已上線——所以這是**上線後又消失**，你可能不知道。
- 需要你決定：這功能還要嗎？要的話合併分支重 build；不要的話把分支與記錄清掉。
- 工作量：**小**（若要復原）

### A5. 安全網的失效模式是「靜默全開」

兩件事合起來看：

**(a) 認證 fail-open**——`app/deps.py:209-210` 與
`poc/kb-mcp/mcp_http_gateway.py:100-101` 都是「讀不到 token 就放行」。

> **校準**：實測目前 `/` 與 `/mcp` 都回 401，plist 裡兩個 token 都有設，
> **現在沒有在漏**。問題不是現在起火，是煙霧偵測器沒電時會自己說「一切正常」。
> 一次 plist 編輯失誤，公開 ngrok 網址上 47 個 MCP 工具（含全部寫入工具）就無認證。

**(b) 不知道正式服務正在跑哪份 code**——uvicorn PID 56897 啟動於 2026-09-10，
期間 `git reflog` 顯示工作樹切去 `docs/*` 分支又切回並前進 3 個 commit。
這次剛好只動到 `.jsx` 沒事，但 KeepAlive 重啟會載入**當下 checkout 的任意分支**。

- 修法：認證改 fail-closed（沒 token 就拒絕啟動）＋ 加 `/api/version` 端點，
  或把正式服務移到獨立的 git worktree（推薦，一勞永逸）
- 工作量：**半天**（兩項合計）

> **✅ 2026-09-17 已完成**（worktree 未做，見下）。
> **認證**：`app/deps.py` 新增 `assert_auth_configured()`，兩個 token 分開
> 檢查，缺任一個就**拒絕啟動**，除非明確設 `ALPHAVIBE_ALLOW_NO_AUTH=1`
> （沿用 `ALPHAVIBE_ALLOW_PRODUCTION_WRITE` 的雙旗標慣例）。請求層另有
> 第二道 fail-closed。刻意不動 `mcp_http_gateway.py`——它與已退役的
> `report_server.py` 共用，改它要連帶改 1,139 行測死碼的測試；改在
> `app/routers/mcp.py`，正式流量的實際入口。
> **版本端點**：新增 `/api/version`，回 commit／分支／啟動時間／`dirty`
> 旗標（啟動時工作區有未 commit 改動）。
> 新增 `app/tests/test_auth.py` 13 個測試——本專案 `app/tests/` 底下
> **第一支真正的 unittest**（B2 的第一步）。
> **未做**：獨立 prod worktree。`/api/version` 已能回答「跑的是哪份 code」
> 這個問題，worktree 是更徹底但會改變部署結構的做法，留待 PO 決定。

---

## B. 高投資報酬（投入小、痛感大）

### B1. `report.py` 有 76% 是死碼，而你一直在改它

- `poc/kb-mcp/report.py` 2,870 行中 **2,190 行不可達**（AST 可達性分析；
  `app/` 的實際進入點只有 11 個符號／516 行）。
- **鐵證**：它是近 90 天 churn 第一名（24 commits），而且**退役後的 6 次 commit
  有 4 次改的是死碼**（`95a5059`/`c712c8b`/`66b8f2c`/`0fffc7f`）。
- 連同 `report_server.py`(912行，確認可刪) 與 `tests/test_report_server.py`(1,139行) 一起清。
- 工作量：大（但前兩步只要 **1 天就拿到 80% 收益**）

### B2. `app/tests/` 裡的不是測試

- 已獨立驗證：`test_smoke.py`(647行) 與 `test_quick_input.py`(280行) 的
  `def test_` 數量都是 **0**。它們是手寫腳本，`unittest discover` 一個都收不到。
- 對比：`poc/kb-mcp/tests` 實跑 **869 tests OK, 9.085s**，那邊是真的在保護你。
- 也就是說：**正式服務那一層等於沒有自動化測試**。
- 工作量：1-3 天

### B3. 前端沒有任何 Error Boundary

- 全 24 檔 grep 0 命中。`StockDetail.jsx` 等頁面深度解構後端回應且無防禦檢查，
  後端結構一有落差就整棵樹白畫面，你在手機上會看到全白、沒有任何線索。
- 工作量：小（一個 ErrorBoundary 包住 `<Outlet/>`）

> **✅ 2026-09-17 已完成**。`web/src/components/ErrorBoundary.jsx` 兩層掛載：
> `AppShell` 包住 `<Outlet/>`（頁面崩潰時導覽列還在，可切去其他分頁）＋
> `main.jsx` 最外層防線。關鍵細節是 **`key={pathname}`**——沒有它，error state
> 不會自己清掉，使用者一旦踩到錯誤連切分頁都切不出去，比白畫面更像壞掉。
> 已 rebuild `web/dist/`（正式服務直接讀磁碟，不必重啟即生效）。
> 驗證：17 項契約與掛載檢查全過；獨立驗收另以 `vite build` 重新建置比對，
> 與現有 `dist/` 逐位元組相同（含 content-hash 檔名），確認原始碼真的進了產物。
>
> 附記：一度想用 SSR（`renderToString`／`renderToPipeableStream`）做端到端驗證，
> 兩次都不成立——error boundary 的 fallback 在 SSR 需要 Suspense 邊界，SSR 不是
> 驗證它的正確工具。改為驗證元件對 React 契約的實作＋掛載位置，並誠實記錄限制：
> **沒有瀏覽器環境的端到端測試**，因為專案沒有前端測試框架，加一個超出本批範圍。

### B4. 排程失敗會被靜默吞掉

- 實例：log 裡找到 2026-09-14 TPEx + 興櫃 SSL 失敗，沒有任何通知。
- 加上 6 個 launchd 的 log 都沒有輪替機制（目前最大 592KB，會無上限累積）。
- 工作量：小～中

> **✅ 2026-09-17 已完成**。
> **巡檢**：`poc/kb-mcp/check_scheduled_jobs.py`，每天 04:00
> （`com.alphavibe.healthcheck`）。偵測資料源失敗、掃描覆蓋率驟降、排程
> 沒跑、備份缺失或異常小。**用 9/13–9/14 的真實歷史資料驗證過**：當天
> 會報 3 個 CRITICAL（TPEx 與興櫃 SSL 失敗、覆蓋率只有 54%）。
> **通知**：Telegram（`poc/kb-mcp/notify.py`，直接打 Bot API，不 import
> 閘道專案的程式碼，通知因此不依賴閘道服務是否在跑）＋ STND 首頁橫幅
> （`/api/jobs/health` → `web/src/components/JobHealthBanner.jsx`）。
> 只在**狀態變化**時發通知——每天固定發一則「還是壞的」會讓人麻痺，
> 麻痺的告警等於沒有告警。橫幅同理，只在 critical／warning 時出現。
> **log 輪替**：`poc/kb-mcp/rotate_logs.py`，每天 03:45
> （`com.alphavibe.logrotate`），單檔超過 5MB 才輪替，保留 5 份。
> 用 copy-truncate 而非 mv——實測確認 launchd 用 append 模式，輪替後
> 服務繼續寫同一個 file handle（mv 會讓 log 靜默消失）。
> 測試：`test_check_scheduled_jobs.py` 22 個。

### B5. 分支債

- 可安全刪除 **8 個**｜需先合併 **3 個**｜需人工判斷 **2 個**
  （`function/stnd-gateway-web` 見 A4、`claude/substack-article-discussion-8c62eh`
  有 13 commits 含 599 行新測試檔且無文件追蹤）
- 另有 origin 上 11 個 cloud-session 遠端分支殘留。
- 工作量：小（但需要你判斷那 2 個）

---

## C. 明確不用花錢的部分

審查特別確認了這些**寫得好、不要動**：

- **依賴方向單向乾淨**：`poc/` 從不 import `app/`（2 處命中全是 docstring）
- **`app/` 零裸 SQL**：6 處命中全是註解
- **資料目錄雙旗標防呆紮實**（`ALPHAVIBE_DATA_DIR` + `ALPHAVIBE_ALLOW_PRODUCTION_WRITE`）
- **`us_stock_store.py` 是比 `kb_store.py` 更好的示範**——要抽共用時以它為範本
- **`server_readonly.py` 白名單零 drift 且有測試釘住**
- **3 組循環依賴全部是有意識管理的**，建議別動
- **新模組都小而純**（`pnl.py`/`price_position.py`/`exit_signals.py` 等）——
  巨型檔案問題只集中在 4 個舊檔，不是全面性的
- 前端：`StockComboChart.jsx` 是良好的跨市場重用範例；深色模式 token 覆蓋完整；
  手機表格 overflow 處理良好；`QuickInputPanel.jsx` 雖 487 行但內部拆分良好

---

## D. 建議執行順序

| 批次 | 內容 | 工作量 | 為什麼是這個順序 |
|---|---|---|---|
| **第一批：止血** | A2 rollback ＋ A3 備份 ＋ B3 ErrorBoundary | **約半天** | 三件都是小改動，但擋掉「資料靜默損壞且無法回復」與「手機白畫面」兩類最難查的故障 |
| **第二批：安全網** | A5 認證 fail-closed ＋ 正式服務獨立 worktree ＋ B4 排程告警 | 1-2 天 | 讓系統出事時會「叫」，而不是安靜地繼續錯 |
| **第三批：對帳** | A1 資產試算公式核對 | 1-3 天 | 需要你提供原始素材才能做，所以排在你有空的時候 |
| **第四批：減重** | B1 死碼清除 ＋ B2 補真測試 | 3-5 天 | 不緊急，但每拖一週你就多改幾次用不到的程式碼 |
| **隨時可做** | A4 管家分頁去留 ＋ B5 分支清理 | 小 | 需要你先做決定 |

**不建議現在做**：`kb_store.py` Mixin 拆分、台美股共用層抽取、前端 `Assets.jsx`
拆檔、CSS 去重——這些都是真問題但不咬人，等上面做完再看。

---

## E. 交叉比對時發現的錯誤（已校準）

誠實記錄，因為這影響你對報告的信任度：

1. **測試運維 agent 的 curl 證據不成立**：它用 `curl localhost:8080` 宣稱驗證了
   管家分頁消失，但正式服務首頁回 **401 Basic Auth**，它根本沒拿到 JS bundle。
   結論對，理由錯——真正成立的證據是磁碟上的 `web/dist/` grep。
2. **`mcp_http_gateway.py` 不是死碼**：我最初的假設與派工前提都寫錯了。
   `app/routers/mcp.py:41,70,96,99` 正在用它服務手機連接器，退役的只是它的
   獨立 8082 埠外殼。後端 agent 主動推翻了這個錯誤前提。
3. **A5 的嚴重度被高估**：agent 的描述容易讓人以為現在正在裸奔，實測是安全的。

## F. 未驗證事項

- `web/dist/` 是 gitignore 產物，與 `web/src/` 是否同步無法確認
- `poc/kb-mcp/tests/` 全套 869 tests 實跑通過（測試運維 agent，9 秒完成，
  可信且未觸發 FinMind）；但後端 agent 因顧慮 FinMind 額度未跑，兩者不衝突
- A1 的「1~2% 誤差」來源未追查
- `app/tests/` 兩個腳本未實際執行（需先建 `poc/data-test` 複本，本次審查禁止建檔）
