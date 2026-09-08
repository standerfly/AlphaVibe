# API Contract: 新增的 MCP 工具

**Feature**: 001-entry-exit-foundation | **Date**: 2026-09-02
**對應 pre-spec 缺口**：GAP-R01（API contract）

本階段新增 **2 個唯讀 MCP 工具**。兩者都支援「單一標的」與「全部標的」
兩種模式（省略 `code` ＝ 全部），滿足 FR-011 的批次查詢需求。

## 工具一：`get_position_pnl`

**用途**：查詢持股的 FIFO 損益（已實現＋未實現）。

**inputSchema**

```json
{
  "type": "object",
  "properties": {
    "code": {
      "type": "string",
      "description": "台股代碼，如 2330；省略＝回傳全部有交易紀錄的標的"
    }
  }
}
```

**回傳（單一標的模式）**

```json
{
  "code": "2337",
  "name": "旺宏",
  "cost_method": "FIFO",
  "fees_included": false,
  "status": "ok",
  "realized_pnl": 12345.6,
  "unrealized_pnl": -2345.0,
  "unrealized_pct": -4.12,
  "shares_held": 450.0,
  "cost_basis": 56900.0,
  "current_price": 126.0,
  "price_date": "2026-08-31",
  "suspected_duplicates": 2,
  "shortfall_shares": null,
  "note": "金額為毛額，未扣手續費與證交稅"
}
```

**回傳（全部模式）**

```json
{
  "count": 60,
  "cost_method": "FIFO",
  "fees_included": false,
  "positions": [ { ...同上結構... } ],
  "summary": {
    "ok": 39,
    "history_incomplete": 21,
    "no_price": 0,
    "no_trades": 0
  }
}
```

**status 值域**：`ok`／`history_incomplete`／`no_price`／`no_trades`
（判定順序見 `data-model.md`「狀態轉換」節）。

**錯誤與降級**（不拋例外，一律用 status 表達）
- 單一標的查不到交易紀錄 → `status: "no_trades"`，其餘數值欄位為 null
- 賣出超過買進 → `status: "history_incomplete"` ＋ `shortfall_shares`，
  已實現損益仍回傳「配得上批次的部分」，未實現欄位為 null
- 查不到現價 → `status: "no_price"`，`realized_pnl` 照常回傳，
  `unrealized_pnl`／`unrealized_pct` 為 null
- 全部模式下，任一標的的問題**不影響**其他標的（FR-011）

## 工具二：`get_price_position`

**用途**：查詢現價在歷史收盤價區間中的相對位置。

**inputSchema**

```json
{
  "type": "object",
  "properties": {
    "code": {
      "type": "string",
      "description": "台股代碼；省略＝回傳全部有股價歷史快取的標的"
    }
  }
}
```

**回傳（單一標的模式）**

```json
{
  "code": "2337",
  "status": "ok",
  "percentile": 62.5,
  "current_price": 126.0,
  "price_date": "2026-08-31",
  "sample_size": 96,
  "range_start": "2026-04-13",
  "range_end": "2026-09-02",
  "low": 91.8,
  "high": 166.5,
  "basis": "以 96 筆快取收盤價計算（2026-04-13~2026-09-02）"
}
```

**status 值域與門檻**（沿用 `review_engine` 既有常數語意）

| status | 條件 | percentile |
|---|---|---|
| `ok` | 樣本 ≥ 30 | 實際百分位 |
| `limited` | 6 ≤ 樣本 < 30 | 回傳值但 `basis` 必須明講樣本不足 |
| `insufficient` | 樣本 < 6 | **null**（不輸出數字） |
| `no_data` | 該標的無任何歷史快取 | null |

**關鍵約束**：`insufficient`／`no_data` 時 `percentile` MUST 為 null，
**不得**回傳 0 或任何會被誤讀為「在歷史最低點」的預設值（FR-009）。

## 註冊位置（實作時三處都要改）

| # | 檔案 | 位置 | 內容 |
|---|---|---|---|
| 1 | `poc/kb-mcp/server.py` | `TOOLS` list（範本見 `get_trade_ledger` at `server.py:439-448`） | 兩個工具的 name／description／inputSchema |
| 2 | `poc/kb-mcp/server.py` | dispatch 分支（`server.py:820` 起；`get_trade_ledger` 在 `:968-969`） | `if name == "get_position_pnl": ...` |
| 3 | `poc/kb-mcp/server_readonly.py` | `READONLY_TOOLS` set（`:22-32`） | 兩個工具名稱加入白名單 |

**已知陷阱**：目前**沒有任何測試**在守門 `READONLY_TOOLS` 白名單或
`len(TOOLS)`（實測 grep 在 `tests/` 下 0 命中）——漏加白名單不會被測試
抓到，工具會在 Cline 那條唯讀路徑上「靜默消失」。實作時應一併補上
守門測試。

**順手校正**：`server_readonly.py:7-9` 的 docstring 數字已過時
（寫「40 個工具／23 個唯讀」，實際為 43／26；本階段完成後應為 45／28）。

## 明確不在本階段的介面

- 報告頁面（`report.py`／`app/`）不新增任何端點或顯示（FR-013，階段B）
- 不新增任何寫入工具——兩個工具皆為唯讀
- 不修改既有工具的簽名或回傳結構
