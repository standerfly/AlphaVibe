# AlphaVibe 開發路線圖與進度（Roadmap）

> 目的：讓**任何**接手的 session——不論主對話模型是 Sonnet、Opus 或其他，
> 或是 Cline——都能只靠本檔案＋所指文件繼續開發，不依賴任何對話記憶。
> 維護規則：完成一個階段就更新狀態欄（含日期與證據）；改動計畫本身
> 需 PO 同意並在 clarification-log 留紀錄。

## 階段總覽（2026-08-09 更新：1e/1f 補正真實狀態＋庫存買賣圖表整合）

| 階段 | 內容 | 狀態 | 證據 |
|------|------|------|------|
| 0. 需求工程 | product-spec 補完＋主軸重塑（FR-001~025、Q-001~032） | ✅ 完成 | product-spec.md Status: Accepted（2026-07-08） |
| 1a. PoC：MCP 知識庫 | alphavibe-kb server（8 工具） | ✅ 完成 | commit 2297d45；測試 10/10；fresh agent 驗收 PASS |
| 1a+. PoC 擴充：追溯快照層 | snapshots/sources/holdings 三表＋4 新工具（共 12），report.py 快照/持股區塊（SRC-010、Q-034~036） | ✅ 完成 | 2026-07-09；測試 21/21 |
| 1a++. PoC 擴充：選股篩選（第一層＋第二層原型） | 第一層 `screen_stocks`（候選清單手動篩選）＋第二層 `run_market_scan`（TWSE/TPEx批次API全市場初篩＋FinMind補回檔幅度，框架鎖定產業別，每天02:00排程自動跑），手機可用（`/screen`、`/market-scan` 網頁） | ✅ 完成 | 2026-07-22；測試 148/148；fresh agent 驗收 PASS |
| 1a+++. PoC 擴充：部位管理／加碼系統（FR-038~043） | 十層決策框架（投資假說＋情境機率評估/寒冬保留比例、加碼Gate/Score、遞減式加碼、組合集中度、重新估值、減碼三分類＋錨點抗恐慌、風險評分）存進 `raw/部位管理*.md`（SRC-011）＋product-spec §5-K＋Layer 1 哲學庫 `framework_evidence_based_position_sizing`；程式面只做了組合集中度需要的「投資主題標籤」（FR-041/042） | ✅ 完成 | 2026-07-24；測試 175/175 |
| 1b. 試用累積 | PO 日常使用：聊資訊→選股→估值→確認入庫；加碼/減碼討論時套用部位管理框架、建倉時標記投資主題 | 🔄 持續進行（資料持續累積，供模組G未來使用） | 已累積28+檔立場（2026-07-24查證） |
| **1b+. 需求重新盤點＋product-spec全面重寫** | 依1b實測發現多處「文件與實際行為不同模式」（entry_condition/time_horizon 0%使用、snapshots表0筆使用、部位管理十層框架0%採用率等），PO與Claude完整討論（2026-07-25~27）產出「策略引擎＋每日PDCA」的 A-G 模組新架構，product-spec.md／scope-decision.md／clarification-log.md 全面更新 | ✅ 完成 | 2026-07-27；`requirements-rescoping.md`（討論全紀錄，含fresh-context agent通盤審查抓到4嚴重+5建議、PO逐項裁決）；product-spec.md重寫後fresh agent驗收10項條件（9直接PASS，1項小落差已修正） |
| 1e. 模組A+D+E開發 | 老芋頭交易結構化表（FR-044）、交易流水表（FR-056）、策略檢視引擎四組成部分（FR-051~055：通用檢視層/策略專屬層/老芋頭動向比對/部位控制建議）、每日排程整合（FR-057） | ✅ 完成（2026-08-09查證修正，先前本檔誤標待啟動） | commit `4fa230e`（2026-07-31）；`review_engine.py`／`module_d_scheduler.py`；MCP工具`check_general_review`/`check_strategy_review`/`check_laoyutou_signal`/`check_position_control`/`record_module_d_findings`/`run_module_d_check`已掛載server.py |
| 1f. 模組F開發：儀表板方案A＋個股清單/詳情頁＋庫存買賣圖表 | FR-058單頁式儀表板（今日重點/新候選/觀察庫存/策略設定/快速輸入）；個股清單頁＋詳情頁（`/dashboard/stocks`／`/dashboard/stock/<code>`，搜尋/篩選/背景刷新）；庫存買賣圖表（清單頁迷你走勢、詳情頁價格折線＋買賣力道長條圖） | ✅ 完成（2026-08-09查證修正，先前本檔誤標待1e完成） | commit `4fa230e`（2026-07-31，基礎儀表板）＋本機 Cline session `552c625`（2026-08-02，未commit的已完成工作，2026-08-09補commit保存：個股清單/詳情頁、背景刷新機制、`fundamentals_client.py`估值來源架構修正）＋本次session（2026-08-09，庫存買賣圖表嫁接進上述架構，見下方接手指南）；測試600/600綠 |
| 1g. 模組G：策略績效回顧 | FR-059 | ⏳ 待樣本量足夠再啟動（1e/1f已完成，資料寫入管道已對，可持續累積） | — |
| 2. 正式產品 | speckit 流程＋交易紀錄整合 FR-022/FR-056 | ⏳ Phase 1 驗證後（五項前置開放問題已於2026-07-27全數定案，見下方「Phase 2 正式產品」節，但「現在啟動Phase 2」本身仍是待PO另外決定的獨立問題，不是自動觸發） | — |

Deferred（已定案遞延，見 scope-decision.md）：Docker 雲端部署、多用戶、
全域投資助理、n8n、自動通知、部位管理Score量化評分/風險評分（Q-039未
翻案部分）、Feedback Loop。**全市場條件篩選已於2026-07-27正式解禁改列
In-Scope（Q-042），不再屬於此清單**。

## 已知限制／待辦（2026-07-22 記錄，PO 確認「這件事得解決」）

- **第二層全市場批次篩選（`market_scan.py`）目前不涵蓋興櫃**：TWSE／TPEx
  的批次 PER 端點都只有上市/上櫃，興櫃沒有官方批次 PER/PBR 端點（已於
  2026-07-22 研究確認），所以 Stage A 的候選初篩完全排除興櫃股。
  **已知的技術解法（尚未實作）**：TPEx 有興櫃月營收批次端點
  `GET /openapi/v1/t187ap05_R`（354家公司，含產業別、官方年增率欄位，
  跟現有 `market_scan.py` 用的上市/上櫃營收批次端點同一種資料形狀）——
  可以先用這個端點依產業別＋營收年增率初篩出興櫃候選（跟現有 Stage A
  邏輯一致），但這批候選缺 PER（無批次端點），需要對篩出的**小批次**
  候選逐檔呼叫既有的 `tpex_client.get_emerging_stock_valuation()`
  （這個專案已經在用的興櫃逐檔估值函式，含完整 caveats 精確度警語）
  補 PER 估算，才能算出 PEG。實作時要接進 `run_scan()` 的 Stage A→B
  流程，且要在頁面/回報裡沿用 `get_emerging_stock_valuation()` 既有的
  caveats 精確度警語（興櫃估值本來就比上市櫃粗略，不能混為一談）。

- **Layer 1 哲學庫「啟動時自動拼接進 system prompt」（product-spec.md
  FR-014）目前沒有實作**（2026-07-24 查證確認）：`poc/kb-mcp/server.py`
  只實作 MCP `tools` capability，沒有 `resources`/`prompts`，也沒有
  initialize 階段讀取 `poc/data/philosophy/*.md` 的邏輯；`save_philosophy`
  /`get_philosophy` 是純被動檔案讀寫工具，存進去不會讓未來新對話自動套用。
  **目前的權宜做法**：專案 CLAUDE.md「常用查證點」用一行指向重要哲學
  模組路徑，靠使用端（Claude Code 會自動載入 CLAUDE.md）間接觸發；真正
  要做到「存了就自動生效」需要新增 MCP resources capability 或啟動腳本，
  屬於 Phase 2 前可評估的技術債，非阻塞。

- **類股資金流追蹤（FR-032~037）已改列 Deferred**（2026-07-24 查證確認，
  Q-041）：2026-07-12 新增時只寫進 product-spec.md v1 摘要行，從未走過
  scope-decision.md 的正式範圍決策流程，也與同文件 Out-of-Scope「自動
  通知」自相矛盾；加入後 12 天零實作（無資料表、無 ETL、無測試，git log
  只有一條純文件 commit）。已同步修正 product-spec.md／scope-decision.md
  ／clarification-log.md（Q-041）。待未來有明確需求與資源時再重新提案
  ——**注意**：全市場條件篩選（Q-030）已於2026-07-27獨立解禁改列
  In-Scope（Q-042），兩者是分開的決定，類股資金流不因此自動連帶解禁。

- **2026-08-09 查證發現兩層落差，一併記錄**：
  (1) 本檔案「階段總覽」表格在 `4fa230e`（2026-07-31）之後就沒同步
  更新過，1e/1f 狀態欄停留在「⏳待啟動」長達一週以上，接手前務必實際
  查 `git log`／跑測試，不能只看狀態欄——已於本次查證修正（見上方
  階段總覽與1e/1f接手指南）。
  (2) 本機 `function/alphavibe` 一度有一批完整、已測試（590/590）但
  從未commit的工作（個股清單頁/詳情頁/背景刷新架構，2026-08-02本機
  Cline session產出），本檔案完全沒有記錄，只存在於本機working tree、
  一直沒同步。這代表**「開發完成」跟「commit」跟「文件記錄」是三件
  可能各自落後的事**，同一個session換執行環境（例如雲端↔本機）時
  尤其容易漏——已於2026-08-09補commit（`552c625`）並補進本檔案。
  接手任何session：換執行環境或間隔較長時間再接手前，先跑
  `git status`／`git diff --stat` 確認本機有沒有未commit的東西，
  不要假設乾淨。

## 各階段接手指南

### 1b 試用累積（持續進行）
- 執行者：PO 本人（本機或 VS Code tunnel 遠端），用法見 `poc/kb-mcp/README.md`。
- 檢視頁：`python3 poc/kb-mcp/report_server.py`（2026-07-10 起，即時渲染
  ＋iPhone PWA 加入主畫面）；靜態模式 `report.py` 保留備用（2026-07-08）。
- 手機對話（Claude App 自訂連接器掛遠端 MCP）：已查證可行、**暫不做**
  （Q-037，2026-07-10）；未來要做時參考 implementation-options 的路線紀錄。
- **2026-07-27 狀態更新**：完成訊號（≥10檔立場）已達標（28+檔），且
  PO已完成需求重新盤點（1b+），下一步是照 1e→1f→1g 開發模組，不是
  停在「試用累積」——1b 本身持續進行只是為了累積更多資料供模組G使用。

### 1e 模組A+D+E開發（老芋頭表／交易流水表／策略檢視引擎／排程整合）—— ✅ 已完成
- **2026-08-09查證修正**：本節先前寫「待啟動」是誤標，實際已於
  commit `4fa230e`（2026-07-31）完成，見 `poc/kb-mcp/review_engine.py`
  （FR-051~055、FR-057）與 `poc/kb-mcp/module_d_scheduler.py`（CLI排程
  入口）。若要接手改動這塊：先讀 `review_engine.py` 檔頭docstring
  （每個FR的設計取捨都寫在裡面），不要憑product-spec.md文字重新設計。
- **2026-08-16 補記**：「CLI排程入口」不是只有指令碼，2026-08-03起已
  掛 launchd 每天17:00自動跑（`~/Library/LaunchAgents/com.alphavibe.
  moduled.plist`，log證實8/1~8/17每天成功0失敗）——這件事本檔案跟
  `poc/kb-mcp/README.md`都沒記過，一度在另一輪對話裡被誤判成「還沒排
  程」。教訓同上：開發完成／launchd部署／文件記錄是三件可能各自落後
  的事，接手前除了`git log`，`~/Library/LaunchAgents/`跟`launchctl list`
  也要查，不要只看程式碼有沒有寫。詳見`poc/kb-mcp/README.md`「模組D每日
  排程」節。

### 1f 模組F開發：儀表板方案A＋個股清單/詳情頁＋庫存買賣圖表 —— ✅ 已完成
- **2026-08-09查證修正**：本節先前寫「待1e完成」是誤標。完整現況分三批：
  1. **FR-058基礎儀表板**（commit `4fa230e`，2026-07-31）：
     `report.py`的`render_dashboard()`／`render_today_highlights()`／
     策略設定／快速輸入，`report_server.py`提供`/`（新版）與
     `/report-classic`（舊版）並存。
  2. **個股清單頁＋詳情頁＋背景刷新架構**（commit `552c625`，本機Cline
     session產出於2026-08-02，2026-08-09才補commit保存——這批工作
     完成後一直是本機未commit狀態，若接手前發現本機又有類似的未
     commit異動，先跟PO確認是不是同類情況，不要直接捨棄）：
     `GET /dashboard/stocks`（庫存＋研究中標的統一列表，搜尋/篩選/
     分頁，FTS5全文搜尋心得）、`GET /dashboard/stock/<code>`（個股
     詳情頁，資料全部讀快取不即時查外部API）、`POST .../refresh`
     觸發背景執行緒刷新（`report_server.py`的`trigger_stock_refresh()`／
     `is_refreshing()`）、`stock_valuation_snapshots`估值快照快取、
     `fundamentals_client.py`（官方來源優先＋FinMind備援，補齊低流量
     個股查詢路徑的架構原則）、CSV交易紀錄匯入、`server_readonly.py`
     （Cline唯讀MCP wrapper）。
  3. **庫存買賣圖表**（本次session，2026-08-09，PO要求「協助判斷加減碼
     力道」）：嫁接進上述(2)的架構，不是另開新頁面——
     - `kb_store.py`新增`stock_price_history`表＋
       `save_price_history_points()`/`get_cached_price_history()`：
       `review_engine.refresh_price_and_valuation()`背景刷新時本來就
       查過一整段股價序列（改動前只挑最後兩筆存`stock_prices`算漲跌幅、
       其餘丟棄），現在「順便」把整段也存下來，不是多打一次API。
     - `render_stock_list_page()`每列：迷你走勢（`.spark`，讀近60天
       快取歷史，`_sparkline_points()`/`_render_sparkline_svg()`）。
     - `render_stock_detail_page()`「持股與交易」卡：價格折線＋買賣
       力道長條圖（`.combo-chart`，讀`get_cached_price_history()`預設
       近180天，`_combo_chart_aligned_trades()`/`_render_combo_chart_svg()`），
       疊在既有的`.trade-list`精簡清單上方，共用同一張卡片不重複。
     - 首頁「我的庫存與分析」表格代碼欄位改連結到
       `/dashboard/stock/<code>`。
     - 刻意不做：詳情頁走勢圖只在PO點進單一檔＋按「更新」時才會有資料
       （背景刷新才會查價），不是每次開頁面就查；不fallback回FinMind
       （2026-07-28教訓：匿名額度全域共用）。
- 硬約束：Python 3.9 相容、不引外部依賴（沿用 poc 原則，SVG/inline JS
  屬頁面自身內容非外部套件，可用）、繁體中文介面。全數符合。
- 驗收（不可自驗）：本次session已跑600/600測試綠＋用真實TWSE官方API
  （2330台積電）+ playwright screenshot驗證清單頁/詳情頁/首頁三頁渲染
  正常（見對話紀錄，未存檔進repo）——這是開發者自驗，仍須PO在本機
  實際開啟頁面確認、或派fresh agent逐項核對。

### 1f+ 個股詳情頁 PR-review 化（2026-08-19~20）—— ✅ 已完成

依 PO 核准的手機版 mockup，把「加碼審查」從一串扁平 finding 重構成有
結論、有分區、有進度的決策頁。四塊依序完成，每塊都以 8299／2308 真實
資料驗證過（結論與 PR#5／PR#9 兩份 artifact 一致）：

1. **今日重點排序**（`f537c23`）：改以「是否持有」為第一排序鍵（存股>
   觀察中，PO 確認的風險敞口優先序），立場衝突降為同層級內次要排序，
   新增「類型」欄。
2. **集中度／部位控制卡**（`cefadec`）：`review_engine.position_control_
   suggestion()` 本來就算了集中度，但結果只塞進其他 finding 的
   suggested_action 欄位、頁面從來讀不到——等於算了沒顯示。這次直接
   重用該函式畫成進度條＋上限虛線。狀態刻意**三分**（已達上限／未超標／
   無法判斷），「算不出來」不能跟「沒超標」混為一談。
3. **加碼進度卡＋計畫總額度**（`658438b`）：補上 `suggested_add_pct`
   一直缺的分母（新增 `position_plans` 表＋2 個 MCP 工具＋網頁表單）。
   單位是金額（PO 裁決）。「已投入」＝**目前部位成本**不是歷史買進總額。
4. **Verdict banner＋Checks 分區**（`c0059f4`）：**策略層正式移出 Gate**
   ——`check_strategy_review` 檢查的是「還符不符合當初篩選門檻」＝候選
   機制，不是持有／加碼條件。先前把它跟通用層並列，等於把「退出便宜貨
   候選名單」呈現得像「投資假說被推翻」。現在拆成 Required・Gate（紅綠）
   ／Reference only（藍，用詞避開 PASS/FAIL）／Status check（中性），
   結構上就不可能再誤讀。Verdict 置於價格之前（對治成本定錨心魔）。
   資料層新增 `module_d_results.trigger_label`。
5. **Score 四項自動化**（`7fcd8e2`、`34c466f`）：推翻先前「Score 沒有
   資料源」的判斷——實查 FinMind 財報資料集有 EPS／GrossProfit／Revenue／
   IncomeAfterTaxes，七項裡四項算得出來。PO 裁決「EPS 上修」＝實際 EPS
   成長（對去年同季），與「法人上修 EPS」（預估修正，無免費源）區分。

**過程中修好的沉默失效（重要）**：`get_revenue_yoy` 原本只抓 400 天≈13
個月，但年增率要拿去年同月比，13 個月只算得出 **1 筆** YoY——而
`_growth_deceleration` 要求至少 3 筆，所以**成長趨緩檢查上線以來從未
真正運作過**，一律回「資料不足」。改抓 800 天後可算出 14 筆。接手時
若看到某個檢查永遠回「資料不足」，先確認資料窗口夠不夠，不要當成正常。

**額度控制**：新增三張快取表（`revenue_yoy_cache` 20小時去重／
`financial_metrics_cache` 30天／`auto_score_cache` 存結果），詳見
`poc/kb-mcp/README.md`「資料位置」節。動這塊前先讀那張表，別讓每日
排程的 FinMind 呼叫次數悄悄翻倍（2026-07-28 額度被打光的教訓）。

### 1g 模組G：策略績效回顧
- 啟動時機：PO主動觸發，不是排程自動跑；等1e/1f運作一段時間、累積夠
  多市場篩選與檢視樣本後再啟動，避免樣本太小的統計沒有意義。
- 需求依據：product-spec.md FR-059。

### Phase 2 正式產品（前置條件已全數定案，是否現在啟動仍待PO另外決定）
- 前置五項開放問題（2026-07-24~27 PO逐項定案，見clarification-log.md
  Q-025/Q-026/Q-042/Q-043、product-spec.md §11）：
  - Q-025（LLM 用量）：**已定案**，維持不設硬上限
  - Q-026（對話歷史保存）：**已定案**，維持只存已確認入庫內容
  - OQ-2（交易紀錄邊界）：**已定案**，按既有建議（FR-022 只記價位/時間/理由）
  - OQ-1（YouTube 處理）：**已定案（2026-07-27）**，PO自行預處理成心得
    文字檔後自由文字貼入，不開發Cline adapter
  - OQ-3（儀表板形態）：**已定案（2026-07-27）**，方案A單頁式（FR-058）
  - Q-034（服務化與多供應商架構）：**已定案（2026-07-27）**，維持
    local-first，不需要服務化架構
  - watchpoints排程形態（FR-031）：仍未討論，非阻塞（FR-031本身是後行
    Phase 2項目）
- **五項開放問題全數解決不等於「現在就該啟動Phase 2」**——目前PO選擇
  的路徑是繼續在Phase 1 PoC擴充模組A-G（1e/1f/1g），不是跳去走
  speckit流程；啟動Phase 2是獨立的範圍/時機決定，需PO明確表示才進行。
- **2026-08-18 補充（Q-045）：啟動門檻是「使用率」，不是「穩定性」**
  ——這輪對話討論過「擺脫單機依賴的正式部署」（雲端主機/服務化），也
  確實累積了不少單機依賴的真實痛點（環境切換混淆、devtunnel 30%失敗率、
  Write工具hook卡死等）。但PO明確表示：這些痛點不是啟動架構升級的理由，
  **先把服務內容打磨到PO自己會想常態使用、使用率提升，才代表內容真的
  對了，那時候才討論上線／架構升級**——順序是「內容→使用率→架構」，
  不是反過來用架構穩定性去推動使用率。日後真的評估時，PO明確表示
  **優先找免費方案，非必要不接受月費**（哪怕$5-10/月）。接手session
  看到「單機依賴」相關痛點時，不要自行判斷「該修了」就去動架構，先確認
  使用率門檻是否已經跨過。
- 啟動方式（PO決定要啟動時）：「依 handoff-checklist.md 進行 spec-kit
  input 切分」→ 之後走 `speckit-specify` → plan → tasks → implement
  （見 ADR-0027）。

## 給接手 session 的原則（Sonnet 級模型也適用）

1. 先讀本檔案與專案 CLAUDE.md，**不要**從對話記憶或猜測出發。
2. 全域制度照用：派工三件套、驗證不自驗、判斷 rubrics
   （`~/.claude/rules/`，尤其 10/20/30 號檔）。
3. 本專案鐵則：本機只有 Python 3.9（腳本與 poc 都要相容）；poc 零外部
   依賴；文件一律繁體中文；skills 三份拷貝改動要同步。
4. 同一子任務卡住兩輪 → 帶失敗軌跡升級 opus 或停下問 PO，不要硬試第三次。
5. 涉及產品取捨（範圍、優先序、要不要做）→ 整理選項與代價問 PO，不代答。
