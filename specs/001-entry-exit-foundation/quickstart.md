# Quickstart: 進出場分析基礎層

**Feature**: 001-entry-exit-foundation | **Date**: 2026-09-02

## 跑測試

```bash
cd /Users/stander/My_project/AlphaVibe
python3 -m unittest discover -s poc/kb-mcp/tests
```

本功能新增的測試：

```bash
python3 -m unittest poc.kb-mcp.tests.test_pnl -v          # FIFO 各情境
python3 -m unittest poc.kb-mcp.tests.test_price_position -v  # 百分位三段門檻
```

> 測試一律用 `tempfile.mkdtemp()` 建獨立庫，**不會碰到正式庫**
> `poc/data/alphavibe.db`。範本見 `tests/test_holdings_sync.py:24-30`。

## 手動驗證兩個新工具

MCP server 走 stdio，最快的驗證方式是直接呼叫底層函式：

```bash
cd /Users/stander/My_project/AlphaVibe/poc/kb-mcp
python3 - <<'EOF'
from kb_store import KBStore
import pnl, price_position

store = KBStore("../data")          # 唯讀查詢，不寫入
entries = store.get_all_trade_entries()
prices = store.get_stock_prices()

# 單一標的損益
print(pnl.compute_position_pnl("2337", entries, prices))

# 賣超情境（實測 21 檔會是 history_incomplete，例如 6257）
print(pnl.compute_position_pnl("6257", entries, prices))

# 價位定位
print(price_position.compute("2337", store.get_cached_price_history("2337"), prices))
EOF
```

**預期看到的關鍵欄位**：`cost_method: "FIFO"`、`fees_included: false`、
以及賣超標的的 `status: "history_incomplete"` ＋ `shortfall_shares`。

## 驗證資料正確性的方式

FIFO 結果要能與原始交易列對得上（SC-002）。取一檔買賣完整的標的，
手動對照：

```bash
sqlite3 "file:poc/data/alphavibe.db?mode=ro" \
  "SELECT date, action, shares, price FROM trade_ledger WHERE code='2337' ORDER BY date, id;"
```

依 FIFO 規則（先買的先被賣掉配對）手算已實現損益，與工具輸出比對。
**注意單位是「股」不是「張」**——金額即 `股數 × 價格`，不需 ×1000
（見 research.md R-001 的證據）。

## 已知的資料現況（不是 bug，是設計要面對的事實）

| 現象 | 實測數字 | 對應處理 |
|---|---|---|
| 賣出量超過買進量 | 60 檔中 21 檔 | `status: history_incomplete` ＋ 缺口股數 |
| 疑似重複交易列 | 141 筆 ＋ 3 組重複 order_ref | 照原樣計入＋`suspected_duplicates` 警示 |
| 有股價歷史的標的 | 只有 39/60 檔 | `status: no_data` |
| 股價歷史最長深度 | 約 100 個交易日 | 多數會落在 `ok`（≥30 筆），但區間短 |
| 持股快照 avg_cost 缺值 | 最新 23 列中 21 列 | 本功能不依賴它 |
| 手續費／證交稅 | 資料表沒有此欄位 | 損益為毛額，`fees_included: false` |

## FR-014 實測（加長排程抓取窗口）

改 `screener.PRICE_WINDOW_DAYS`（120 → 400）後，**必須**以單一標的
實測外部來源回應正常再收工：

```bash
cd /Users/stander/My_project/AlphaVibe/poc/kb-mcp
python3 -c "
import screener
print(screener.PRICE_WINDOW_DAYS)
rows = screener._fetch_prices_with_fallback('2330')
print('筆數:', len(rows) if rows else rows)
"
```

**只測一檔就好**——2026-07-28 曾因密集測試把 FinMind 匿名額度打光、
連累當晚 02:00 的正式排程（CLAUDE.md 教訓紀錄）。

## 完成後的驗收

依 `~/.claude/rules/10-model-dispatch.md` 第 6 節「驗證不自驗」，
實作完成後應派 fresh-context agent 對照 spec 的 14 條 FR 逐條驗收，
不由實作者自己宣告完成。
