# Phase 0 Research: 進出場訊號層

**Feature**: 002-entry-exit-signals | **Date**: 2026-09-03

所有結論皆附 `檔案:行號` 或實際查詢輸出；查證日期 2026-09-03。
**本階段最高風險是「新增訊號拖慢每日流程」**——階段A 曾因未實測外部
呼叫次數而讓排程慢了 29 分鐘，本文件 R-002 專門處理這件事。

## R-001：門檻儲存採 append-only，不沿用 `position_plans` 的覆寫式

**Decision**：新增 `exit_thresholds` 表，**append-only、最新一筆勝出**
（`max(id) GROUP BY code`），與 `stances` 同模式；**不**採用
`position_plans` 的 `INSERT OR REPLACE`。

**Rationale**：spec 的 Assumptions 明確要求「門檻保留調整歷史」——門檻
背後有討論脈絡，日後要能回答「當初為什麼設在這裡」。repo 內兩種模式
都有先例：

| 表 | 模式 | 有無歷史 |
|---|---|---|
| `position_plans`（`kb_store.py:1053-1070`） | `INSERT OR REPLACE` | 無 |
| `stances`（`kb_store.py:485-514`） | append-only ＋ `max(id) GROUP BY code`（`:478-483`） | 有 |

門檻的語意接近 `stances`（一連串判斷紀錄）而非 `position_plans`
（單一當前設定值），故沿用前者。

**Alternatives considered**：覆寫式加一張獨立歷史表——多一張表、多一條
寫入路徑，收益與 append-only 相同，不值得。

## R-002：新訊號對每日流程的成本必須是「零新增外部呼叫」

**Decision**：三種新訊號（門檻觸發、背離、營收趨勢）**全部只讀既有
已載入或已快取的資料，不新增任何外部 API 呼叫**。

**Rationale**：實測基準線（來自 `module_d_results.checked_at` 真實時間戳）：

| 日期 | 筆數/檔數 | 起訖 | 秒數 |
|---|---|---|---|
| 2026-09-02 | 125 筆 / 39 檔 | 17:00:04→17:13:46（估值刷新至 17:18:21） | **1097（18.3 分）** |
| 2026-09-01 | 118 | 17:00:02→17:12:47 | 765 |
| 2026-08-27 | 91 | 17:00:03→17:32:36 | 1953（異常日） |

主要成本在既有邏輯、不在本階段：`fundamentals_client.get_per_history()`
預設 `window_days=730` → `_months_needed(730)=38` 個月 → **每檔 38 次
TWSE HTTP**，且 `general_review` 呼叫時沒傳 cache（`review_engine.py:257`），
每次 `time.sleep(0.15)`；另 `strategy_specific_review` 每個關聯策略各跑
一次 `screener.screen_stocks([code])`（`:324`）。

三種新訊號的資料來源盤點——**全部命中既有資料**：

| 訊號 | 需要的資料 | 來源 | 新增呼叫 |
|---|---|---|---|
| 門檻觸發 | 現價 | `stock_prices` 表（`get_stock_prices()`），每日流程本來就刷新 | **0** |
| 門檻觸發 | 門檻值 | 新表 `exit_thresholds`（本機） | **0** |
| 背離偵測 | 營收年增率 | `fetch_revenue_yoy()`（`review_engine.py:228-242`），`general_review` 已呼叫過、20 小時快取 | **0**（重用同一份結果） |
| 背離偵測 | 股價位置 | `stock_price_history` 快取（階段A 已回補至 224~267 筆/檔） | **0** |
| 營收趨勢擴大 | 更多期年增率 | 同一份 `fetch_revenue_yoy()` 結果，實測每檔可得 **14 筆非 null YoY** | **0** |

**驗證方式（實作時必做，不可省略）**：攔截 `_throttled_get` 與
`finmind_client` 的呼叫，比較「有無新訊號」兩種情況的外部呼叫次數，
必須完全相同。這是階段A 教訓的直接應用。

## R-003：FinMind 營收與 TWSE 股價的呼叫行為相反

**Decision**：規劃文件必須分開描述兩者，不可套用同一套心智模型。

- **TWSE 股價**（`twse_price_client.fetch_price_history`）：**逐月**抓，
  `_months_needed = window_days // 20 + 2` → 窗口加長＝呼叫次數等比例
  增加。階段A 就是在這裡踩坑（120→400 天使每檔 8→22 次）。
- **FinMind 營收**（`finmind_client.get_revenue_yoy`，
  `REVENUE_YOY_LOOKBACK_DAYS = 800`，`finmind_client.py:179`）：**單次
  date-range 查詢**，一次取回整段。實測每檔 26 列原始、14 筆非 null YoY，
  加長窗口不會等比例增加呼叫。

所以 FR-007 擴大觀察期數（3 期 → 6 期）**零成本**，上限是既有窗口可算出
的 14 期；要超過 14 期才需要動 `REVENUE_YOY_LOOKBACK_DAYS`。

## R-004：FR-007 的實作方式——擴大演算法但維持既有函式的輸出契約

**Decision**：在新模組實作 `revenue_trend(values, periods)`（更穩健的
趨勢判斷），讓既有的 `_growth_deceleration`（`review_engine.py:117-143`）
**委派**給它；`_growth_deceleration` 的**輸出結構與呼叫端介面完全不變**
（仍回 `{"flagged", "detail", ...}`），只有內部判斷準則擴大。

**Rationale**：現況是「最近 3 期（`MIN_YOY_POINTS = 3`，`review_engine.py:77`）
全部為正且嚴格遞減」才 flagged——條件很窄，實測 2026-09-02 當天 39 檔
只有 1 檔觸發（1785，`95%→71%→46%`）。單純把期數從 3 拉到 6 而維持
「嚴格遞減」會讓它幾乎永不觸發（更糟）；改用趨勢判斷（斜率為負＋最新值
低於窗口中位數）才是 FR-007 要的「更穩定的趨勢判斷」。

維持輸出契約可讓三個呈現面（首頁今日重點、詳情頁 Checks 卡、
`module_d_results` 記錄）零改動——**改的是判斷準則，不是介面與資料流**。

**必做的驗證**：實作後用正式庫既有資料跑「改動前 vs 改動後」逐檔比對，
列出哪些標的判斷結果改變、是否合理，寫回本文件。不可只跑單元測試就
宣稱完成。

**Alternatives considered**：另開獨立檢查項、不動既有函式——會讓同一件事
（營收趨勢）出現兩個判斷結果，PO 看到兩筆矛盾的發現更困惑。

## R-005：新訊號走 `module_d_results`，不走 `stances`

**Decision**：新訊號以 `run_module_d_review()` 的 items 形式產出、寫入
`module_d_results`；**不呼叫 `auto_record_findings()`**（那是寫 `stances`
的路徑，`review_engine.py:566-623`）。

**Rationale**：FR-013 明文禁止（PO 裁決 Q1-A）。實測 `stances` 474 筆中
**437 筆是機器自動寫入**、PO 手寫僅 37 筆，且 `list_stances()` 取
`max(id) GROUP BY code`（`kb_store.py:480-481`），每檔的「最新立場」永遠
是機器那筆。新訊號不再加劇此現象。

**附帶好處（零前端改動）**：首頁「今日重點」的篩選謂詞就是
`suggested_action is not None`（`report.py:721`／`app/routers/dashboard.py:108`），
三處（SSR／API／React）都對齊。新訊號只要在 items 多產一筆並填
`suggested_action`，**三個畫面自動顯示**。

`trigger_label` 新增兩值：`通用層／停損停利`、`通用層／背離`
（既有：`通用層／成長趨緩`、`通用層／下檔風險`、`策略層／{id}`、
`老芋頭動向`）。

## R-006：`suggested_action` 只在觸發時填，控制洗版

**Decision**：新訊號**只有實際觸發時**才填 `suggested_action`；未設定
門檻、未觸發、資料不足三種狀態一律不填，只寫入 `module_d_results` 供
詳情頁顯示。

**Rationale**：首頁「今日重點」只顯示 `suggested_action is not None` 的列。
若每檔每天都產生建議，首頁會被灌爆（實測每日已有 11~26 筆自動記錄）。
另外現況 `suggested_action` 內容固定來自 `position_control_suggestion()`
（`review_engine.py:768-769`）——那是**部位大小**建議，與出場建議語意
不同，故在 items 層各自填入，不擴充該函式以免職責不清。

## R-007：門檻設定是寫入工具，不進唯讀白名單

**Decision**：新增 MCP 工具 `save_exit_threshold`（寫入）與
`get_exit_threshold`（唯讀）。**只有 `get_` 版本加入
`server_readonly.py` 的 `READONLY_TOOLS`**。

**Rationale**：FR-004 明文——設定門檻是寫入操作，唯讀路徑依設計看不到
也用不到。與既有 `save_position_plan`／`get_position_plan` 的處理一致
（白名單只有 `get_position_plan`）。

## R-008：FIFO 與加權平均估算並存的呈現（FR-014／FR-015）

**Decision**：頁面同時顯示兩個數字，各自標明口徑：

- FIFO 可算出時：以 FIFO 為主，標註 `FIFO・未扣交易成本`
- FIFO 回 `history_incomplete` 時：顯示「FIFO 無法計算：歷史不完整
  （缺口 N 股）」＋既有加權平均估算值，標註
  `加權平均估算・未扣賣出・非 FIFO`
- 走勢圖均價虛線：兩種情況都沿用既有 `_avg_cost_for_chart` 的估算值，
  圖例加註口徑（避免 1/3 標的的虛線消失）

**Rationale**：PO 裁決 Q2-C。實測 60 檔中 21 檔賣超，單純替換會讓 PO
每天在看的頁面上 1/3 標的突然空白。

**改動點（4 處）**：`report.py:1922-1942`（`_chart_stats_html`）、
`report.py:1985,1992`（`_holdings_card_html` 呼叫處）、
`app/routers/stock_detail.py:188,194-206`、
`web/src/pages/StockDetail.jsx:299`。走勢圖虛線（`report.py:1993`）
維持現狀。

**注意**：階段A 的 `pnl.py` 目前只被 MCP 工具消費，`app/` 與 `web/` 零
引用——本階段是它第一次接進 UI 資料管線。

## R-009：排程 log 缺時間戳，先補上再談監控

**Decision**：在 `module_d_scheduler.py` 的輸出加上起訖時間戳與逐階段
耗時，作為 FR-012 的量測基礎。

**Rationale**：實測 `~/Library/Logs/alphavibe-module-d.log` 只有
`module_d_scheduler完成：trigger=scheduled total=39 ...` 這種摘要行，
**完全沒有時間戳**——本次基準線只能從 `module_d_results.checked_at`
反推。FR-012 要求「執行時間增幅可被量測」，沒有時間戳就無從驗證。

順帶修正三處不一致：實際排程是 **17:00**（plist），但
`review_engine.py:834` 註解寫 18:00、`server.py:600` 註解寫 02:00。
