# AlphaVibe 測試品質與運維狀態審查報告

審查日期：2026-09-17｜審查者：唯讀審查 agent（未修改/建立/刪除任何 repo 檔案、
未重啟任何 launchd 服務、未 checkout/merge 任何分支）

---

## 總覽

- 測試檔：`app/tests/` 2 個（皆非 unittest，procedural black-box script）＋
  `poc/kb-mcp/tests/` 23 個 unittest 檔（原始需求說 25/27，實際盤點為
  2+23=25 個檔案，14425+927=約 15352 行）
- `poc/kb-mcp/tests`：**869 個 unittest test method，全部 PASS**（用
  `.venv/bin/python3`，9.085 秒，見下方第4節證據）
- `app/tests/`：因唯讀限制無法建立測試資料庫複本，**未實際執行**，改用
  靜態程式碼審查（見第4節說明）
- launchd 常駐/排程服務：6 個現行 + 1 個備援(devtunnel，仍在跑)+ 2 個
  已停用備份
- 本地分支：15 個（不含當前 `function/alphavibe`），另有 11 個純遠端
  `claude/*` cloud-session 分支

---

## 1. 測試的真實覆蓋（分類）

逐檔判斷後的分類（依附件抽樣＋規則式掃描，非逐行讀完全部15000行）：

**(a) 真正驗證商業邏輯的（具體輸入→預期輸出斷言）**：poc/kb-mcp/tests 的
絕大多數檔案都屬此類，包含 test_kb.py(117)、test_report.py(95)、
test_review_engine.py(67)、test_trade_ledger_parser.py(65)、
test_us_stock_store.py(55)、test_traceability.py(55)、
test_twse_price_client.py(43)、test_screener.py(38)、
test_market_scan.py(37)、test_exit_signals.py(34)、
test_trade_text_parser.py(33)、test_us_stock_mcp_server.py(28)、
test_us_trade_text_parser.py(18)、test_fundamentals_client.py(18)、
test_pnl.py(17)、test_us_stock_scan.py(16)、test_holdings_sync.py(14)、
test_price_position.py(12)、test_benchmark.py(10)、
test_module_d_scheduler.py(8)、test_us_stock_price_client.py(5)。抽查
test_benchmark.py／test_module_d_scheduler.py 確認斷言具體到數值
（`assertAlmostEqual`、`call_count`、特定 kwargs），非空泛檢查。
`app/tests/test_smoke.py`（無 unittest method，procedural script，約28項
PASS/FAIL 檢查）與 `test_quick_input.py` 屬同類但形式不同——皆會拿 API
輸出跟直接呼叫底層函式（`screener.screen_stocks()`／
`get_latest_market_scan()`／`_tracked_stock_rows()`）比對，是本次審查
遇到品質最高的測試設計，含 30 併發請求的 race-condition 回歸測試。

**(b) 純淺層檢查（只驗 200/不拋例外）**：抽樣未發現任何檔案「整檔」屬此類；
即使是 HTTP 層測試（test_report_server.py）也驗證了狀態碼＋標頭＋auth
邏輯等具體行為，不是純粹的煙霧檢查。

**(c) 測試已退役/死碼**：
- `test_report_server.py`（1139行/63測試）——直接 spawn
  `report_server.ReportHandler`。查證：正式服務已於 2026-08-22 起改跑
  `uvicorn app.main:app`（`app/main.py` 沒有 import `report_server`，
  改成直接 import `poc/kb-mcp/*.py` 底層函式），`report_server.py`
  本身不再被任何生產路徑 import 或執行（`grep "import report_server"`
  全 repo 掃描為 0 筆非測試命中）。這 63 個測試驗證的 HTTP 外殼
  （ReportHandler.do_GET/do_POST）已無正式流量會經過。
- `test_mcp_http_gateway.py`（21測試）**部分**死碼：`MCPHTTPGatewayTest`
  class（11測試）spawn 獨立 `mcp_http_gateway.MCPHandler` + 
  ThreadingHTTPServer，對應的獨立閘道服務（:8082）已由
  `com.alphavibe.mcphttpgateway.plist.disabled-20260822` 確認停用；但
  `HandleMcpPostDirectCallTest`（6測試）與`PathTokenMatchesTest`（5測試）
  測的是純函式`handle_mcp_post()`/`mcp_method_not_allowed()`，這兩個函式
  **仍被** `app/routers/mcp.py` 正式 import 使用（`import mcp_http_gateway`），
  不是死碼。

---

## 2. 測試的可信度陷阱

**CSS 字串誤判（已知教訓 2026-08-19 復發）**：寫了程式掃描
`test_report.py` 全部 202 個 `assertIn/assertNotIn(..., page)`，逐一比對
`report.py` 內嵌 CSS 常數（17762字元）是否含有同一字串。找到 **7 處**
高風險斷言，會在對應功能實際壞掉時仍然通過（因為 CSS 區塊本身就包含
該字串，跟功能是否正確渲染無關）：
- L48 `assertIn("#c92a2a", page)` —— 該色碼是 CSS `--red` 變數定義，每頁都有
- L821 `assertIn("var(--red)", page)` —— CSS 規則本身就用到這個值
- L883 `assertIn("has-concern", page)` —— 是 CSS class 選擇器名稱
- L909 `assertIn("is-up", page)` —— 同上
- L950 `assertIn("集中度／部位控制", page)` —— 是 CSS 內的中文註解文字
  （諷刺的是同一測試下方緊接著有註解正確示範要用 `class="conc-fill`
  前綴比對，顯示作者知道這個坑，但沒有把同樣的檢查套用到這個斷言本身）
- L1098 `assertIn("disabled", page)` —— CSS 選擇器/屬性名也含此字串
- L1107 `assertIn("reason-pin", page)` —— CSS class 名稱

這些斷言不是完全無效（同一測試方法通常還有其他更獨特的文字斷言，如
「老芋頭於2026-07-30賣出500股」，能提供實際保護），但這 7 處本身對
「該 class 是否真的被渲染出來」這件事沒有偵測力。對照組：`test_report_server.py`
（0/86）、`test_traceability.py`（0/32）、`test_review_engine.py`（2/54，
經查為 dict key 'price' 非 HTML，屬掃描誤報）——問題集中在 test_report.py，
沒有擴散到其他檔案。

**真實外部 API 呼叫**：檢查所有 `requests.get/post`、`urlopen`、
`finmind_client`／`yfinance` 相關呼叫，**未發現任何測試會打真實外部
API**——`urlopen` 的命中全部是測試自己起的 localhost HTTP server
（test_report_server.py／test_mcp_http_gateway.py／app/tests的黑箱測試），
FinMind／TWSE／yfinance 全部經 `unittest.mock.patch` 替身。869 個測試
9 秒內全部跑完也印證了這點（若真打外部 API 不可能這麼快）。

**吞掉失敗的 try/except 或恆真斷言**：全庫掃描 `except: pass`、
`skipIf/skipUnless/SkipTest` 模式，**均為 0 命中**，沒發現此類問題。

---

## 3. 缺口（最該補測試的地方，依風險排序）

1. **`app/routers/assets.py` 的情境試算金額計算（`_simulate_asset_scenario`／
   `_accumulation_balance_at_month`／`_withdrawal_balance_at_month`／
   `_build_curve_points`，L297-416）——零測試覆蓋**。全 repo grep 這4個
   函式名稱／`/api/assets/simulate`，只有定義它們的 `assets.py` 本身命中，
   沒有任何測試檔案引用。這是複利年金公式（累積期一般年金終值、提領期
   反推年金公式），有 `r==0` 除以零的特殊分支處理——這正是「金額計算」
   類別裡風險最高、最該有單元測試的程式碼，且是 2026-09-10 才新增的
   新功能（PO 只能用手動視覺檢查驗證圖表對不對，見同日 commit
   「情境試算推演圖補X軸年份刻度」）。**工作量：中**（純函式，容易寫
   `assertAlmostEqual` 表格式測試）。
2. **`app/routers/assets.py` 整體黑箱測試覆蓋率低**：該 router 定義 13 個
   路由（544行，是全部 router 中最大的），但 `test_smoke.py`／
   `test_quick_input.py` 只打了 3 個（`/pockets`、`/accounts`、
   `/holdings` 的 GET）。**完全沒打到**：`/simulate`、
   `/net-worth-history`（含 manual/delete）、`/contributions`（含
   delete）、`/buildup/{id}/months/.../complete`、`.../undo`、
   `/pockets/{id}/archive`、`/accounts/{id}/archive`。工作量：中。
3. **`app/routers/stock_detail.py`（266行，`/api/stocks/{code}`）完全沒有
   任何黑箱測試命中**——這是個股詳情頁的核心 API，同樣量級的
   `holdings.py`／`market_scan.py`／`screen.py` 都有 smoke test 比對，
   唯獨這支沒有。工作量：小～中。
4. **`app/routers/mcp.py`（`/mcp`、`/mcp/{token}`）沒有透過 app/ 黑箱測試
   驗證**——底層純函式在 `test_mcp_http_gateway.py` 有測，但 FastAPI
   router 層本身（token 驗證、路徑白名單接線）沒有端到端驗證。工作量：小。
5. **`app/routers/us_stocks.py` 的 `/holdings`、`/price-history`、
   `/stance` 三個 GET 端點未被 smoke test 覆蓋**（其餘 us-stocks 端點都
   有覆蓋）。工作量：小。

次要觀察：`frameworks.py`（91行）只在 test_traceability.py 被呼叫一次
`default_framework_id()`，未見對其規則邏輯本身的獨立測試——因檔案小、
變動少，列為觀察項不列入前5。

---

## 4. 測試能不能跑（實際執行證據）

**`poc/kb-mcp/tests`**（`.venv/bin/python3 -m unittest discover -s poc/kb-mcp/tests`）：
```
Ran 869 tests in 9.085s
OK
```
Exit code 0。（提醒：若用系統 `/usr/bin/python3` 而非 `.venv/bin/python3`
執行，會有 4 個 ERROR——`ModuleNotFoundError: No module named 'yfinance'`
命中 `test_us_stock_price_client.py`——純粹是直譯器選錯，`.venv` 裝有
yfinance 1.2.0，不是程式碼問題。)

**`app/tests/test_smoke.py`／`test_quick_input.py`**：**未執行**。這兩支
測試依規定必須指向一份獨立測試資料庫複本（`poc/data-test/`，不存在，
文件建議 `cp -R poc/data poc/data-test` 後清空資產表），但本次審查是
唯讀任務、明確禁止建立任何檔案（scratchpad 報告檔除外），因此未建立
該複本、未執行這兩支測試。改以靜態程式碼審查其設計品質（見第1、5節），
不對其實際執行結果做任何宣稱。**這是本報告唯一「未驗證,只查了程式碼」
的項目，如實標註，不編造執行結果。**

---

## 5. 運維與可觀測性

**服務清單**（`launchctl list` 實際查詢）：
| Label | 狀態 | 型態 |
|---|---|---|
| com.alphavibe.reportserver | 執行中 (PID 56897) | KeepAlive 常駐，:8080 |
| com.alphavibe.ngrok | 執行中 (PID 807) | KeepAlive 常駐，固定網域 |
| com.alphavibe.devtunnel | 執行中 (PID 813) | KeepAlive 常駐（備援，見下） |
| com.alphavibe.marketscan | 待機（僅排程時執行） | 每天 02:00 |
| com.alphavibe.moduled | 待機 | 每天 17:00 |
| com.alphavibe.usstockscan | 待機 | 每天 06:00 |

**服務掛了會不會知道**：`reportserver`／`ngrok` 都設 `KeepAlive=true`，
process 掛掉 launchd 會自動重啟（自我修復），但**沒有任何機制通知使用者
發生過重啟/崩潰**——不看 log 不會知道曾經掛過。若是 ngrok 雲端中繼層本身
的問題（非本機 process 崩潰，例如帳號/網域層級問題），本機完全偵測不到，
使用者只能等到自己嘗試遠端連線失敗才發現。**未發現任何主動 uptime 監控**
（無 cron/launchd 定期打 ngrok 網址自我檢查，`crontab -l` 為空）。

**log 是否會塞爆磁碟**：查證 `/etc/newsyslog.d/`、`newsyslog.conf`，
**沒有為任何 alphavibe log 設定輪替**，plist 本身也沒有大小上限機制，
是 launchd 預設的無限累加寫入。目前實際大小：`alphavibe-ngrok.log`
592KB、`alphavibe-report-server.err.log` 552KB、`alphavibe-report-server.log`
269KB、`alphavibe-market-scan.log` 22KB，其餘皆 <10KB——**現況離塞爆磁碟
還很遠**，但這些是長駐/每日排程服務，數個月到數年尺度會持續累積且無上限。

**排程失敗有沒有通知**：`market_scan.py`／`module_d_scheduler.py` 完全
沒有 Telegram/email/push 通知機制（grep 全部命中皆為 0）。**找到一筆
實際發生過的靜默降級案例作為佐證**：`alphavibe-market-scan.log` 顯示
2026-09-14 02:07 那次執行，TPEx 與興櫃兩個資料源都因
`SSL: CERTIFICATE_VERIFY_FAILED` 整批失敗，但排程仍標示「完成」
（只是候選數變少），這種「部分資料源掛掉但整體看起來正常結束」的情況，
使用者不會被告知，只能自己發現當天候選股數異常偏少才會起疑。相對地，
`us_stock_scan.py` 已經有 `notify_telegram()`（重用 telegram_gateway 的
設定與 Bot token，L87-130）可以推播──但目前只用在監控條件觸發的業務
通知（FR-012），沒有延伸到「排程本身失敗/資料源降級」這種運維層級的
通知，是現成機制没有物盡其用的缺口。

**ngrok 免費層風險**：現況設定使用固定網域
`chancefully-erosive-lilian.ngrok-free.dev`（付費或免費層某種固定域名
方案），比純隨機網域穩定，但仍是第三方雲端中繼層，且已知教訓記錄過
「瀏覽器 UA 會被導向 ngrok 警告頁」的問題（2026-09-10 已修）。免費層
的連線數/頻寬限制與帳號層級中斷風險本次未做壓力測試驗證，標註「未驗證」。

**devtunnel 備援服務仍在執行**：`com.alphavibe.devtunnel.plist`
（KeepAlive=true，跑 `devtunnel host puzzled-dog-fxqxsq2`）自
2026-07-31 建立至今仍在跑（PID 813），但 CLAUDE.md 2026-07-31 教訓紀錄
明講「確認 ngrok 穩定後可 `launchctl bootout`...停用」——ngrok 已穩定運作
超過一個半月，這個備援服務理應可以關閉但至今仍占用資源／持續寫 log。

**Python 直譯器選擇**：`marketscan`／`moduled` 兩個 plist 用系統
`/usr/bin/python3`（stdlib-only，經查 market_scan.py／module_d_scheduler.py
確實只 import stdlib＋本地模組，不需要 venv 套件，這樣設定沒有問題）；
`usstockscan.plist` 正確使用 `.venv/bin/python3`（因為 us_stock_scan.py
需要 yfinance）——**已檢查，無發現**，兩種選擇都對應各自腳本的真實依賴。

---

## 6. 分支債

**可安全刪除（已完全合併進 function/alphavibe，0 個獨有 commit）—— 8 個**：
`003-us-stocks`、`claude/delta-electronics-research-6lr0qx`、
`docs/mark-position-plan-done`、`docs/nvidia-ai-chain-pricing-research`、
`function/assets-net-worth-chart`、`function/us-stocks`、
`function/us-stocks-mcp-wiring`、`function/us-stocks-yfinance-fallback`。
（`develop` 技術上也是 0 獨有 commit，但因它是 ADR-0027 文件明訂的正式
基底分支，不建議當「垃圾」刪除，見下方單獨說明。）

**需先合併（有獨有 commit，但內容單純、風險低）—— 3 個**：
- `claude/investment-strategy-review-uejd7p`：1 commit，純文件（roadmap+README）
- `docs/edge-ai-supply-chain-research`：3 commits，純新增研究筆記檔
- `docs/photography-research-and-reorg`：2 commits，純新增研究筆記＋roadmap

**需人工判斷 —— 2 個**：
- **`function/stnd-gateway-web`**（2 commits，`Gateway.jsx` 411行＋CSS，
  共1661行新增）——**這是本次審查發現的最嚴重問題**：查證發現
  `Gateway.jsx` 完全不存在於 `function/alphavibe` 分支（`git show
  function/alphavibe:web/src/pages/Gateway.jsx` 回報路徑不存在），且
  **直接對正式服務發 GET 請求（`curl localhost:8080`）確認目前實際被
  服務的 JS bundle 裡完全沒有「gateway」或「管家」字樣**——換句話說，
  memory 記載「2026-08-30/31 已完成上線」的 STND 網頁「管家」分頁，
  **現在已經不在正式環境裡了**，很可能是 9/10 前後在 `function/alphavibe`
  分支上重新 `npm run build`（例如當天的資產走勢卡功能）時，因為那個
  分支沒有 Gateway.jsx，覆蓋掉了原本含有 Gateway 頁面的 `web/dist`
  建置產物（`web/dist` 未進版控，純本地檔案，沒有任何機制防止舊建置
  被沒有該功能的分支覆蓋）。這代表 PO 現在打開 STND 網頁應該看不到
  「管家」分頁——除非 PO 其實已經知道且是刻意的，否則這是一個沒人
  發現的正式環境功能回歸。建議：(1) 立刻跟 PO 確認「管家」分頁是否
  真的消失了，(2) 若非刻意，需要合併 `function/stnd-gateway-web` 進
  `function/alphavibe` 並重新 build `web/dist`。
- **`claude/substack-article-discussion-8c62eh`**（13 commits，含新檔
  `test_research_brief.py` 599行、`analysis_mode硬性程式閘門`等實質
  功能與測試，1775行新增/4行刪除，最後一次 commit 2026-08-12）——這是
  一批完整、有測試佐證的功能開發，但完全沒有合併進主線，也沒在
  roadmap.md／clarification-log.md 等文件中找到後續追蹤紀錄（未逐字搜尋
  全文，僅檢查分支本身內容），需要 PO 判斷這批工作是否還要、或已被
  後續其他方式取代。

**遠端殘留（origin 上的純 cloud-session 分支，補充觀察，非本次主要要求）**：
另外 11 個 `origin/claude/*` 分支未在本地簽出。其中 9 個各只有 1
commit、內容都是「chore: gitignore __pycache__」——查證 `.gitignore`
第6行已經有 `__pycache__/`，這 9 個分支的修改已經完全冗餘，是重複
session 各自獨立發現同一個問題的殘留，可以安全從 origin 刪除。另外
2 個內容較多：`origin/claude/taiwan-ai-infrastructure-analysis-wehi3w`
（3 commits，庫存買賣圖表）——CLAUDE.md 2026-08-09 教訓紀錄已明確記載
「雲端那個分支的獨立實作已判定不再需要merge」，可安全刪除；
`origin/claude/watchlist-feature-discussion-uzo3ga`（7 commits，「待觀察/
待查詢清單功能，全部20個任務」）——未在任何文件找到後續處置紀錄，且
現有 `us_stocks.py` 已有語意相近的 watch-conditions 功能，**懷疑但未
證實**兩者是否重複/已被取代，建議人工判斷（本項推測成分較高，標註
「未驗證」）。

---

## 檢查角度清單（供覆蓋度判斷）

1. 逐檔 `def test_` 計數 + mock 使用量統計（grep 交叉比對）
2. 全庫 grep 真實網路呼叫模式（requests/urlopen/finmind/yfinance）
   排除 mock/patch 上下文
3. 寫程式抓取 report.py 的 CSS 常數內容，逐一比對 test_report.py／
   test_report_server.py／test_review_engine.py／test_traceability.py
   全部 assertIn/NotIn 字串是否為假陽性風險（非人工抽查，是完整字串比對）
4. 模組↔測試檔命名對照，找出「有模組沒對應測試檔」的落差，逐一人工確認
   是否真的沒測到（部分透過其他測試檔的 import 間接覆蓋）
5. 路由清單（grep `@router.` decorator）↔ 黑箱測試涵蓋的路徑逐條比對
6. 實際執行 `.venv/bin/python3 -m unittest discover`（先用系統 python3
   跑過一次發現直譯器選錯問題，再用正確 venv 重跑取得可信結果）
7. `launchctl list` + 逐一讀取 6 份現行/2份停用備份 plist 全文
8. 讀取所有對應 log 檔案大小與尾端內容，找出實際發生過的失敗案例
   （非只看程式碼理論上會不會失敗）
9. 對正式服務（localhost:8080）發真實唯讀 GET 請求，比對「文件宣稱
   已上線的功能」與「實際被服務的內容」是否一致——這步驟意外挖出
   第6節最嚴重的發現
10. `git branch --merged/--no-merged` + 逐分支 `git log A..B --oneline`
    + `git diff --stat` 交叉確認，並延伸查了 origin 上未簽出的遠端分支
