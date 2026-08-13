# alphavibe-kb — 三層知識庫 MCP server（Phase 1 PoC）

對應 spec：`docs/spec-intake/alphavibe/product-spec.md`（FR-015~021、Q-021
即時確認制）與 `implementation-options.md` Phase 1。純 Python 標準庫
（本機 Python 3.9，官方 MCP SDK 需 3.10+ 故不引依賴）。

## 用法（Claude Code）

repo 根目錄的 `.mcp.json` 已註冊本 server。在 AlphaVibe 目錄**開新的
Claude Code session**，首次會詢問是否啟用 `alphavibe-kb`——允許後即可：

- 「幫我把剛剛討論的台積電看法存進知識庫」→ AI 呼叫 `save_stance`，
  **工具核准提示＝你的確認**（Q-021）；與既有立場衝突時會先被擋下、
  列出新舊立場請你決定（FR-013/018）
- 「查一下 2330 的基本面」→ `get_fundamentals`（FinMind 即時數據）
- 「6826 和淞的本益比大概多少？」→ `get_emerging_stock_valuation`（興櫃股估值
  粗估，FinMind 的 PER 資料集不含興櫃股；回傳一定附精確度限制說明）
- 「我對哪些股票有立場？」→ `list_stances`
- 「搜尋知識庫裡關於法說會的評論」→ `search_comments`
- 「更新一下我持股的股價」→ `refresh_holdings_prices`（寫入快取，檢視頁
  下次重新整理就會顯示最新市值/持股比例）
- 「幫我篩選這幾檔：3485,6953,6719」→ `screen_stocks`（第一層候選清單篩選，
  預設依 PEG＜1 且回檔≥40% 框架；可傳 `framework_id` 套用 `frameworks.py`
  裡的其他框架，或直接傳 `peg_threshold`/`drawdown_min`/`drawdown_max` 自訂
  門檻，傳 `null` 代表這項條件不看；回傳同時附超額跌幅與大盤基準脈絡。
  手機也可直接開 `/screen` 網頁表單篩選，見下）
- 「幫我掃一次全市場」→ `run_market_scan`（第二層批次篩選，見下；也可開
  `/market-scan` 網頁按鈕觸發，或等每天 02:00 排程自動跑全部框架。回傳給
  AI 的是精簡摘要＋符合框架的候選，不是全部候選——完整清單要用
  `get_market_scan` 查）
- 「上次全市場掃描結果是？」→ `get_market_scan`（只查快取，不重新掃描；
  預設只回傳符合框架、精簡欄位、最多 50 筆，回傳一定附 `total_results`/
  `returned`/`omitted` 讓 AI 知道有沒有被截斷；要完整資料傳
  `meets_only=false, limit=0, verbose=true`）

## 工具清單

| 工具 | 層 | 說明 |
|------|-----|------|
| save_stance / get_stance / list_stances | L2 | 個股立場（含衝突擋下機制，保留歷史） |
| save_comment / search_comments | L3 | 盤勢評論，FTS5 trigram 全文檢索（**查詢至少 3 個字**） |
| save_comments_batch | L3 | 一次存入多筆評論（欄位同 save_comment）；個別筆缺必填欄位只該筆失敗，不影響其餘筆數存入 |
| save_philosophy / get_philosophy | L1 | 投資哲學模組 md 檔（append/replace）；篩選框架（如 framework_v1）也存這裡 |
| save_snapshot / get_snapshots | 追溯 | 分析結論凍結（當時價/估值/三段式結論/框架版本）＋引用來源；歷次快照供 diff（FR-026~028） |
| save_holdings / get_holdings | 追溯 | 持股快照 {code, shares, avg_cost, date}——不含損益計算（FR-029、Q-035 邊界） |
| refresh_holdings_prices | 快取 | 批次更新目前庫存每檔的股價（近 7 天最新收盤價）與產業別快取，供檢視頁算市值/持股比例、顯示產業別；不帶參數，個別代碼失敗只記入 failed 不中斷整批。檢視頁本身不即時呼叫外部 API，靠這個工具定期寫入快取——建議每個交易日跑一次 |
| save_stock_alias / get_stock_alias | 輔助 | 股票名稱→代碼查證快取，避免同一檔股票重複查證（同名再存＝更新） |
| parse_holdings_report | 輔助 | 解析券商零股庫存表原始文字，擷取每列 code/name/shares（`*`前綴標 is_emerging）；純解析不寫入資料庫，需人工確認後再呼叫 save_holdings 入庫 |
| get_fundamentals | 數據 | FinMind：近期 PER/PBR/殖利率＋近 6 月營收 |
| get_stock_info | 數據 | FinMind：股票基本資料（名稱/產業分類/市場別）；不帶代碼查全部 |
| get_stock_price_history | 數據 | FinMind：個股股價歷史 OHLC＋成交量，預設近 90 天 |
| get_revenue_yoy | 數據 | FinMind：月營收年增率（FinMind 無此欄位，自行以去年同月計算；缺去年同月資料標 null） |
| get_institutional_trading | 數據 | FinMind：三大法人買賣超，預設近 30 天，額外回傳 foreign_net（外資淨買賣超加總） |
| get_balance_sheet | 數據 | FinMind：最近一期資產負債表現金/負債概況（現金及約當現金／流動負債合計／負債總額／資產總額），附 debt_ratio（負債總額/資產總額，機械計算）。無官方優先來源 |
| prepare_research_brief | 研究 | SRC-013 Stage 1（候選FR-060）：機械蒐集現有資料源＋依買進前研究checklist七節骨架排版，**不含任何AI判斷或敘事**。財務體檢五節有實際數字（查詢失敗時 status=query_failed）、三節無資料源（status=no_data_source，毛利率/現金流/法說會Q&A）；頂層業務理解/產業結構/預期差/破裂條件/估值敘事/收斂四問六節本質是判斷，status固定為needs_discussion，需另外對話討論、結論寫回save_stance。**Stage 2**：可選參數`peers`——不帶時，用一次`get_stock_info`全量查詢帶出同產業候選名單`peer_candidates`（不逐檔查財務資料，避免浪費FinMind額度）；帶peers（如`["2303"]`）時，對每個peer重跑財務體檢五項並排放入`peer_comparison`，純數字不含評語/排名。兩欄位互斥 |
| get_emerging_stock_valuation | 數據 | 興櫃股估值粗估（PER/PBR，資料源 TPEx OpenAPI 興櫃三端點＋FinMind 淨值）；FinMind 的 PER 資料集不含興櫃股才需要這個工具。**精確度低於正式上市櫃股**（EPS 僅半年報/年報、非 TTM 基礎；PBR 股數為資本額估算值），詳見回傳的 caveats 欄位 |
| screen_stocks | 篩選 | 第一層選股篩選：對候選代碼清單逐檔計算 PEG（本益成長比）與近 120 天股價回檔幅度＋超額跌幅（個股回檔－同期大盤跌幅，大盤區間取「個股高點日→個股最新日」），依門檻標註是否符合框架。預設「PEG<1 且回檔≥40%」（`framework_peg_deep_dip_concentration`）；可傳 `framework_id` 套用 `frameworks.py` 裡的其他框架（代號不存在直接回 error、不打任何 API），或傳 `peg_threshold`/`drawdown_min`/`drawdown_max` 自訂門檻（`null`＝不看這項條件，跟「沒給這個參數」語意不同）；單檔失敗只記入該筆 error，不中斷整批；一次最多 50 檔。純候選清單篩選，不是全市場掃描 |
| run_market_scan | 篩選 | 第二層全市場批次篩選：Stage A 用 TWSE/TPEx 官方批次 PER＋月營收年增率 API（含 PBR／殖利率），在框架鎖定的產業別（半導體業/電子零組件業/其他電子業）內快速初篩候選；Stage B 對候選逐檔查 FinMind 補股價回檔幅度與超額跌幅。TWSE/TPEx 任一資料源失敗不影響另一邊。**完整候選（含未達門檻、全部欄位）連同時間戳存入資料庫**，但回給 MCP 呼叫端的是瘦身過的摘要（run 統計＋符合框架的候選精簡欄位＋`note` 提示如何取完整清單）——避免單次回傳超過 MCP 上限被截斷。範圍只有上市＋上櫃，興櫃不在批次掃描範圍（無官方批次PER端點）。**這是 Q-030（scope-decision.md 列為 Deferred）的原型驗證，尚未正式解禁全市場篩選** |
| get_market_scan | 篩選 | 查詢最近一次全市場批次篩選結果，不重新掃描，秒級回應。預設 `meets_only=true`／`limit=50`／`verbose=false`（只回符合框架的候選、精簡欄位、最多 50 筆），回傳一定附 `total_results`/`returned`/`omitted`/`filters`/`available_frameworks`，避免把截斷後的少數幾筆誤當成全部候選母體；要完整資料傳 `meets_only=false, limit=0, verbose=true` |
| save_laoyutou_trade / get_laoyutou_trades | 追溯 | 老芋頭（訊號來源，非系統使用者）交易結構化表（FR-044）：{code, name, action, shares, price, date, reason（可為空）, source_ref}；`get_laoyutou_trades` 不給 code 列最近N筆（跨標的），給 code 列該標的歷史，供模組D「老芋頭動向比對」（FR-053）使用 |
| save_trade_ledger_entry / get_trade_ledger | 追溯 | PO 自己的交易流水表（FR-056，跟老芋頭交易表是兩張不同的表）：{code, name, action, add_sequence（第幾次加碼，僅買入適用，賣出強制存 NULL）, shares, price, date, source_ref}；`get_trade_ledger` 依日期由舊到新回傳，供 FR-054 遞減式加碼比例計算推算下一次加碼序號 |
| check_general_review | 模組D | FR-051 通用檢視層：不管哪個策略篩進來的標的，每檔都要過的一致性提醒（不自動裁決，決策權在PO）。這次只自動算2項——成長趨緩（近3個非null月營收年增率是否連續下滑，且仍是正成長）、下檔風險（PE壓縮模型：目前PER相對近2年歷史分布是否偏高，資料點≥30用90百分位數門檻，不足則退回用歷史最大值9成當簡化門檻，偏高時附「PE回歸歷史中位數」的潛在跌幅粗估）。財報兌現度／利多出盡／預期獲利能否持續上修這3項尚未自動化（需另串TWSE/TPEx季度財報API與MOPS公告，屬後續工作），回傳的 `manual_notes` 欄位（一律 None）留給PO手動填寫，本工具純計算、不寫入資料庫 |

追溯性用法示例：「分析完了，幫我把這次結論存成快照，附上剛剛查證的來源」；
「這是我的持股截圖，解析後存快照」；「列出 6805 的歷次快照，比對我當時的判斷」。

## 檢視頁

**即時模式（推薦，手機適用）**：
```bash
python3 poc/kb-mcp/report_server.py        # 佔用 8080，取代 http.server
```
每次瀏覽器重新整理都即時讀資料庫重新渲染——不必再手動重跑產出。
沿用既有 devtunnels 轉發網址（開 `/` 或舊路徑 `/poc/data/report.html` 都通）。

**iPhone 加入主畫面（假 App）**：Safari 開 devtunnels 網址（首次登入帳號）
→ 分享 → 「加入主畫面」→ 主畫面出現 AlphaVibe 圖示，點開全螢幕。
電腦入庫新資料後，手機下拉重新整理即見。

**靜態模式（備用）**：`python3 poc/kb-mcp/report.py` 產出
`poc/data/report.html`＋圖示檔，適合離線留存單一時點快照。

內容：立場總覽（紅多綠空）＋分析快照＋持股快照（含市值/持股比例/產業別，
讀 `refresh_holdings_prices` 寫入的快取，未執行過則顯示「未更新價格」）＋
最近 20 則評論＋哲學模組清單＋免責聲明。「理由」欄位超過 40 字自動摺疊，
點擊展開看全文。兩種模式同為 OQ-3（儀表板技術形態）的實驗——1c 前的過渡
工具，刻意不含即時股價（市值用的是定期更新的快取，非即時報價）與距離
目標買價（FR-024 儀表板的事）。

**第一層選股篩選（手機可用）**：即時模式下另有 `/screen` 網頁表單——貼入
股票代碼（逗號或換行分隔）、送出即看到 PEG/回檔幅度/超額跌幅篩選結果，
符合框架的列以黃底標出。標題文字（門檻條件）依實際套用的門檻動態組字，
不是寫死的字串。全程網頁操作，不經過 Claude 對話，解決手機上 Claude Code
chat 面板不穩定的問題。靜態模式不支援（表單需要伺服器處理送出的請求）。

**第二層全市場批次篩選（手機可用）**：`/market-scan` 網頁——框架下拉選單
＋「立即掃描」按鈕（同步執行，實測約30秒）＋最近一次結果表格（含觸發方式
手動/排程、TWSE/TPEx 異常橫幅、大盤基準異常橫幅）。結果拆成「符合框架的
候選」與「全部候選」兩個區塊，欄位含 PER/營收年增率/PEG/回檔幅度/超額
跌幅/PBR/殖利率；摘要列有資料時會多顯示「同期大盤回檔 X%」（舊 run 沒有
這個值就整段不顯示，不會顯示假的 None）。每天 02:00 由 launchd 排程
（`com.alphavibe.marketscan`，見下）自動跑一次全部框架，不用手動觸發也會
有最新結果可看。框架清單在 `poc/kb-mcp/frameworks.py`，**目前有兩個框架**：
`peg_deep_dip_concentration`（PEG＜1 且回檔≥40%，list 第 0 位＝預設框架）
與 `revenue_high_price_dip`（營收年增率＞30%、回檔 15~40%、不看 PEG，
依超額跌幅排序）；下拉選單自動列出全部框架，不用改網頁程式碼。框架若有
量化規則做不到、需人工判斷的條件（如 EPS 是否持續上修），頁面上「這個
框架有哪些條件是工具查不到、需要人工判斷？」收合區塊會列出來。新增/修改
框架用講的，不做資料庫編輯介面。

**排程服務**：`~/Library/LaunchAgents/com.alphavibe.marketscan.plist`，
`StartCalendarInterval` 每天 02:00（不是 `RunAtLoad`+`KeepAlive`，跟
`reportserver` 常駐服務不同——這是跑一次就結束的批次工作）。改排程時間
要重新載入 plist 才會生效（`launchctl kickstart -k` 只重啟已載入的定義，
**不會**重讀 plist 內容）：
```bash
launchctl bootout gui/501/com.alphavibe.marketscan
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.alphavibe.marketscan.plist
```
想立刻測試一次不等明天 02:00：`launchctl kickstart -k gui/501/com.alphavibe.marketscan`
（這種情境不是要重讀時間，用 kickstart 沒問題）。log 在
`~/Library/Logs/alphavibe-market-scan.log`。

## 資料位置

`poc/data/`：`alphavibe.db`（SQLite，已 gitignore）＋ `philosophy/*.md`。
可用環境變數 `ALPHAVIBE_DATA_DIR` 覆寫。

## FinMind token（可選）

匿名呼叫已實測可用（2026-07-08），額度較低。頻繁使用時到
https://finmindtrade.com 免費註冊，token 放環境變數 `FINMIND_TOKEN`
或 `poc/data/finmind_token.txt`（已 gitignore）。

## 測試

```bash
python3 -m unittest discover -s poc/kb-mcp/tests -v
```

涵蓋：儲存層（立場衝突流程、中文全文檢索、哲學檔案）、FinMind 解析
（mock）、MCP 協定端到端（真實子行程握手＋工具呼叫）、screen_stocks 篩選
邏輯（PEG/回檔/超額跌幅計算、單檔失敗不中斷整批、代碼數量上限、自訂門檻與
框架代號）、benchmark 大盤基準計算（區間回檔、失敗不丟例外）、/screen 網頁
表單（GET/POST，mock）、market_scan 全市場批次篩選（TWSE/TPEx 各自獨立
失敗、產業別過濾、代碼合併、PBR/殖利率解析、多框架 CLI 與共用快取、
CLI 入口）、/market-scan 網頁表單（GET/POST，mock）、server.py MCP dispatch
（screen_stocks 門檻覆寫語意、無效框架代號不打 API、run_market_scan／
get_market_scan 輸出瘦身與 total_results/returned/omitted 計數）、
`test_traceability.py` 對 `TOOLS` 固定 32 個工具的斷言（含 FR-044 老芋頭
交易表、FR-056 交易流水表的 4 個工具、FR-051 通用檢視層的 check_general_review）。
