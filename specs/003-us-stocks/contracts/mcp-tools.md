# API Contract: 美股獨立 MCP 工具

**Feature**: 003-us-stocks | **Date**: 2026-09-06
**格式比照既有先例**：`specs/001-entry-exit-foundation/contracts/mcp-tools.md`
**部署位置**：新檔案 `poc/kb-mcp/us_stock_mcp_server.py`（獨立 server，不掛在
既有 `server.py`／`server_readonly.py` 下），對應 `research.md` §2 的獨立
查詢管道決策。所有工具內部只呼叫 `USStockStore`（`us_stock_store.py`），
不 import 任何 `kb_store.py` 或既有台股工具的程式碼。

本階段新增 **9 個工具**，對應 spec.md 的 17 條 FR。

---

## 工具一：`parse_and_save_us_trade`

**用途**：解析使用者截圖轉譯出的交易文字，經 agent 於對話中確認無誤後，
寫入 `us_trades` 表（對應 FR-002/003/004）。**不接受圖片參數**——辨識
步驟在呼叫這個工具之前，由 Claude 讀圖轉成文字完成（見 `research.md` §3）。

**inputSchema**

```json
{
  "type": "object",
  "properties": {
    "text": {
      "type": "string",
      "description": "已由使用者確認過的交易明細文字，格式：每行一筆，包含日期/代號/買賣/股數/價格"
    }
  },
  "required": ["text"]
}
```

**回傳**

```json
{
  "status": "ok",
  "saved_count": 1,
  "trades": [
    {"ticker": "NET", "trade_date": "2026-08-05", "action": "buy", "shares": 10, "price": 298.40, "amount": 2984.00}
  ],
  "parse_issues": []
}
```

`parse_issues` 非空時列出無法解析的行（供 agent 提示使用者修正後重新
呼叫），但**已成功解析的部分照樣寫入**（FR-003：「不論辨識完整度，一律
經人工核對才落庫」——核對已在呼叫此工具前於對話中完成，工具本身不阻擋
部分成功的情況）。

---

## 工具二：`get_us_holdings`

**用途**：依 `us_trades` 彙總計算目前持股（FR-013 美股 landing 清單用）。

**inputSchema**：`{"ticker": {"type": "string"}}`（省略 = 全部）

**回傳**：比照既有 `get_position_pnl` 的單一/全部雙模式慣例，回傳
`shares_held`／`avg_cost`／`realized`（簡化版，不含 FIFO 精算，MVP 只算
簡單加權平均成本，精確 FIFO 損益列為未來擴充）。

---

## 工具三：`get_us_trade_ledger`

**用途**：取得原始交易列表（供股價圖疊加買賣點位，FR-003）。

**inputSchema**：`{"ticker": {"type": "string"}}`（必填，圖表一次只畫一檔）

**回傳**：`us_trades` 表原始列（`trade_date`／`action`／`shares`／`price`）
的陣列，依日期排序。

---

## 工具四：`save_us_stance`

**用途**：把 agent 與使用者討論後的立場與研究筆記存入（FR-008）。

**inputSchema**

```json
{
  "type": "object",
  "properties": {
    "ticker": {"type": "string"},
    "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
    "bear_price": {"type": "number"},
    "bear_price_high": {"type": "number"},
    "base_price_low": {"type": "number"},
    "base_price_high": {"type": "number"},
    "bull_price": {"type": "number"},
    "summary": {"type": "string"},
    "full_note": {"type": "string", "description": "完整研究筆記內容，Markdown格式，FR-009渲染來源，不得省略章節"}
  },
  "required": ["ticker", "direction", "summary", "full_note"]
}
```

---

## 工具五：`get_us_stance`

**用途**：取得個股詳情頁「投資立場」卡片與完整研究筆記內容（FR-005/009）。

**inputSchema**：`{"ticker": {"type": "string"}, "include_closed": {"type": "boolean"}}`

**回傳**：預設只回傳最新一筆 `status='active'` 的立場（含 `full_note`
完整內容，不截斷）；`include_closed=true` 時回傳全部歷史立場列表。

---

## 工具六：`save_us_watch_condition`

**用途**：新增一筆監控門檻（FR-010）。

**inputSchema**

```json
{
  "type": "object",
  "properties": {
    "ticker": {"type": "string"},
    "metric_type": {"type": "string", "description": "例：price, gaap_gross_margin, nrr"},
    "comparator": {"type": "string", "enum": ["lt", "gt"]},
    "threshold": {"type": "number"}
  },
  "required": ["ticker", "metric_type", "comparator", "threshold"]
}
```

---

## 工具七：`get_us_watch_conditions`

**用途**：取得監控條件與目前狀態（FR-011/013）。

**inputSchema**：`{"ticker": {"type": "string"}}`（省略 = 全部）

**回傳**

```json
{
  "conditions": [
    {
      "ticker": "NET", "metric_type": "price", "comparator": "lt", "threshold": 250,
      "status": "ok", "last_evaluated_at": "2026-09-06T06:00:00Z",
      "is_stale": false
    }
  ]
}
```

`is_stale`（衍生欄位，非資料庫實體欄位）：由伺服器比對 `last_evaluated_at`
是否為當日排程執行後計算得出，`true` 時前端顯示「未更新（無額度）」
（FR-017），`status` 欄位本身維持上一次成功評估的值不變。

---

## 工具八：`get_us_price_history`

**用途**：取得股價走勢圖資料（FR-003）。

**inputSchema**：`{"ticker": {"type": "string"}, "days": {"type": "integer", "description": "預設90"}}`

**回傳**：`us_price_snapshots` 依 `snapshot_date` 排序的時間序列
（`close_price`／`snapshot_date`），並標示資料缺口日期（供前端圖表決定
是否要顯示斷點）。

---

## 工具九：`get_us_watchlist`

**用途**：美股 landing 頁追蹤清單彙整查詢（FR-007/013）——四張表的
ticker 聯集，每檔回傳現價、漲跌、立場摘要、監控觸發狀態一次到位，避免
前端要分別呼叫工具一到工具七再自己拼裝。

**inputSchema**：無參數

**回傳**

```json
{
  "watchlist": [
    {
      "ticker": "NET", "name": "Cloudflare",
      "current_price": 286.96, "price_change_pct": -5.95,
      "stance_direction": "bullish", "stance_summary": "偏多．等回檔",
      "watch_status": "alert",
      "is_stale": false
    }
  ]
}
```
