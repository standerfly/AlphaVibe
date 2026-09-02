# Phase 0 Research: 進出場分析基礎層

**Feature**: 001-entry-exit-foundation | **Date**: 2026-09-02

本文件記錄規劃前必須先查證的資料層現況與技術取捨。所有結論皆附
`檔案:行號` 或實際查詢輸出；查證日期 2026-09-02。

## R-001：股數欄位的單位（最高風險項）

**Decision**：`trade_ledger.shares` 與 `holdings.shares` 的單位是
**「股」**，金額 ＝ `股數 × 價格`，**不做任何 ×1000 換算**。

**Rationale**：實際查資料（唯讀）判定——

| 標的 | 交易 | 若為「股」 | 若為「張」 |
|---|---|---|---|
| 3008 大立光 | 買 3 @ 2605 | 7,815 元（零股，合理） | 781 萬元 |
| 3008 大立光 | 買 2 @ 2480 | 4,960 元 | 496 萬元 |
| 2337 旺宏 | 買 80 @ 60.7 | 4,856 元 | 486 萬元 |

本投組 19–23 檔、多為 1–450 的持股數，與「零股交易」型態一致；
若為張，單筆金額動輒數百萬，與投組規模不符。

**Alternatives considered**：初次盤點曾依值域（1–2000、均值 45.9）
推論為「張」——**該推論已證實錯誤**，若照用會讓所有損益金額差 1000 倍。
記錄於此以免後續接手者重蹈。

**Caveat**：`poc/kb-mcp/server.py:270` 的工具描述寫「股數/張數」語意
含混，`:397`／`:431` 寫「股數」。實作時以實際資料為準，並建議順手
統一 `:270` 的描述用字。

## R-002：FIFO 的資料完整性缺口

**Decision**：遇到「賣出股數超過流水表內買進股數」時，回傳
`history_incomplete` 狀態與缺口股數，只計算配得上批次的部分，
不推測缺失批次的成本。

**Rationale**：流水表起始於 2025-11-21，之前的既有部位沒有進場紀錄。
實測 **60 檔中 21 檔**累計賣出 > 累計買進（例：2258 鴻華先進 -6000、
3357 臺慶科 -350、6257 矽格 -280）。任何「補一個假設成本」的做法都會
產出看似精確、實則捏造的損益數字，違反 spec 的 FR-004 與
「算不出來就明講」原則。

## R-003：疑似重複交易列

**Decision**：照原樣計入 FIFO，另回傳 `suspected_duplicates` 警示
（含筆數）。不排除、不修改原始資料。

**Rationale**：PO 2026-09-02 裁決（Q2 選項 A）。實測有 141 筆同
`code/action/shares/price/date` 的多餘列、3 組重複 `order_ref`。
「同日同價買進相同股數」可能是真實交易（分批下單），自動排除有誤刪
真單的風險；沿用 `holdings_sync.py:26-28` 既有的「不回填/修正既有
歷史」決策。

## R-004：現價來源

**Decision**：用 `kb_store.get_stock_prices()` 讀 `stock_prices` 表
（`kb_store.py:84-89`：`code` PK、`price`、`price_date`、`updated_at`），
並在回傳中附上 `price_date`，讓使用者判斷報價新鮮度。

**Rationale**：這是既有的現價快取（`refresh_holdings_prices` 工具寫入），
與儀表板顯示同源，可避免「同一個價格在兩個地方不一致」。符合 spec
FR-010「不為了計算而即時查外部 API」的原則。

**Alternatives considered**：取 `stock_price_history` 的最新一筆收盤價
——同樣可行，但 `stock_prices` 才是既有的「現價」語意來源，且涵蓋
標的較廣（歷史表只有 39 檔）。實作時若某檔在 `stock_prices` 缺席，
再降級用歷史表最新收盤價，並標明來源。

## R-005：歷史股價深度與百分位門檻

**Decision**：百分位只用既有快取（`get_cached_price_history`，
`kb_store.py:872-885`），採三段式降級，門檻沿用 `_downside_risk`
（`review_engine.py:146-201`）的既有常數語意：

| 樣本數 | 行為 |
|---|---|
| ≥ 30 | 回傳真實百分位 |
| 6–29 | 回傳簡化描述（相對區間位置）＋在 `basis` 明講樣本不足 |
| < 6 | 回傳「資料不足，無法判斷」，不輸出任何數字 |

一律附上 `sample_size` 與涵蓋起訖日（FR-008）。

**Rationale**：實測 `stock_price_history` 共 3726 筆 / **39 檔** /
2026-04-13~2026-09-02，**每檔最多約 100 個交易日**。既有
`PERCENTILE_MIN_POINTS = 30`（`review_engine.py:114`）與
`MIN_PER_HISTORY_POINTS = 6`（`:108`）已是本 repo 驗證過的門檻，
沿用可避免另立一套標準。

**Alternatives considered**：線上抓長歷史（FinMind `start_date` 可指定）
——PO 已否決（Q1 選項 C），理由是與「不即時查外部 API」原則衝突且有
額度風險（2026-07-28 曾把匿名額度打光並連累當晚排程）。

## R-006：FR-014 加長排程抓取窗口

**Decision（2026-09-03 修正）**：`screener.PRICE_WINDOW_DAYS` **維持 120**，
改用一次性腳本 `backfill_price_history_once.py` 補歷史深度。

> **原始判斷已被推翻**：本節原本主張把 `PRICE_WINDOW_DAYS` 加長至 400，
> 理由是「加長的是單次抓取的日期範圍，不是抓取次數」——**這個假設錯誤**，
> 由 2026-09-02 的獨立驗收實測推翻，詳見下方「實測結果」。

**原 Rationale（已被下方「實測結果二」推翻，保留供追溯，不要照用）**：
~~這是 `review_engine.refresh_price_and_valuation()` 抓取股價的日期範圍
參數。加長的是單次抓取的日期範圍，不是抓取次數——每檔仍是一次呼叫，
故 API 呼叫「次數」不變。~~
↑ 這段的錯誤在於沒查證 `twse_price_client.fetch_price_history()` 的實作
就假設「一次呼叫」；它其實是逐月抓的。教訓：**涉及外部呼叫成本的宣稱，
必須實際量測呼叫次數，不能從參數語意推論**。

**現行 Rationale**：每日排程（`review_engine.py:863` →
`_fetch_prices_with_fallback(code, None, data_dir, token, None)`）維持
120 天窗口，呼叫次數與本功能開發前完全相同；需要更深歷史時用
`backfill_price_history_once.py` 補一次，`stock_price_history` 是
`INSERT OR REPLACE` 永不刪除，補過就永久有了。

**實測結果一（2026-09-02，T026，只測一檔）**：400 天窗口確實能取得
**268 個交易日**（2025-07-29~2026-09-02），走 `twse_official` 官方端點、
無截斷、未觸發 FinMind fallback。**但這個測試只驗了「資料拿得到」，
沒有量測呼叫次數**——這是 T026 設計上的缺口。

**實測結果二（2026-09-02，獨立驗收攔截 `_throttled_get` 量測）**：
`twse_price_client.fetch_price_history()` 是**逐月**抓的
（`twse_price_client.py:392`，`_months_needed = window_days // 20 + 2`）：

| 窗口 | 每檔月數＝HTTP 次數 | 3 檔實測總次數 |
|---|---|---|
| 120 天 | 8 | 24 |
| 400 天 | 22 | 66（2.75 倍） |

排程路徑 `review_engine.py:863` 傳 `market=None, cache=None`，上櫃股會
先試 TWSE 失敗再試 TPEx（再乘 2），25 檔持股的每日排程會從約 200 次
變成 550+ 次，每次還有 `SLEEP_SECONDS` 節流。這**違反 FR-014 的
MUST NOT 條款**。

**真實世界佐證（2026-09-03 複驗發現）**：`~/Library/Logs/alphavibe-market-scan.log`
顯示 8/22~9/2 的每日排程都在 **02:13~02:14** 完成，唯獨 9/3 那次
（唯一一次在 `PRICE_WINDOW_DAYS=400` 生效下跑的排程）拖到 **02:42:33**，
**晚了約 29 分鐘**——2.75 倍的推算在正式環境確實發生過一次。

**最終做法**：每日窗口維持 120（呼叫次數完全不變），長歷史用
`backfill_price_history_once.py` 補一次。`stock_price_history` 是
`INSERT OR REPLACE` 永不刪除，補過就永久有了，之後 120 天窗口足以接續
更新——長歷史的成本只付一次。守門測試
`test_traceability.test_fr014_daily_window_not_widened` 釘住
`PRICE_WINDOW_DAYS == 120`，避免有人再調大。

## R-007：批次查詢的資料存取

**Decision**：在 `kb_store` 新增 `get_all_trade_entries()`，一次查回
全部交易列（`ORDER BY code, date, id`），由計算層在 Python 內分組。
**不修改**既有的 `get_trade_ledger(code)`。

**Rationale**：既有 `get_trade_ledger`（`kb_store.py:1158-1166`）
必填 `code`，沒有「全部」模式。逐檔迴圈會產生 N+1 查詢（60 檔 → 60 次）。
單一查詢＋Python 分組在本規模（537 筆）成本可忽略，且不動既有方法
可避免影響現有呼叫端。

## R-008：已出清標的的取得方式

**Decision**：標的清單以 **`trade_ledger` 的 distinct code** 為準，
不以 `get_holdings()` 為準。

**Rationale**：`get_holdings()` 無 code 時取「全表最新一天」且帶
`WHERE h.shares > 0`（`kb_store.py:713-745`），**查不到已出清標的**，
與 FR-003「已出清標的仍要回傳已實現損益」直接衝突。
另外最新快照 23 列中 **21 列 `avg_cost` 為空**，也不能當 FIFO 的
成本 baseline 或交叉驗證來源。

## R-009：與既有損益顯示的關係

**Decision**：本階段**完全不動** `report.py:1906-1919`
（`_avg_cost_for_chart`）、`:1922-1941`（`_chart_stats_html`）、
`app/routers/stock_detail.py:188-196`。新工具回傳一律標注
`cost_method: "FIFO"` 與「未扣交易成本」。

**Rationale**：spec FR-013 明文要求。既有三處都是「全部買進加權平均、
不扣賣出、不扣費用」，與 FIFO 口徑不同，兩套數字並存期間必須靠標注
區分，階段B 才整合。
