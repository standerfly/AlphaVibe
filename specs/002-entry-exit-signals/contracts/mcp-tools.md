# API Contract: 階段B 的介面變更

**Feature**: 002-entry-exit-signals | **Date**: 2026-09-03

## 新增 MCP 工具（2 個）

### `save_exit_threshold`（**寫入工具**）

為指定持股設定停損/停利門檻。**只能在具備完整工具存取的主對話使用**
——唯讀路徑（Cline `server_readonly`、`stock-researcher` subagent）
依設計看不到（FR-004）。

```json
{
  "type": "object",
  "properties": {
    "code": {"type": "string", "description": "台股代碼"},
    "stop_loss": {"type": "number", "description": "停損價（絕對價格）；與 take_profit 至少要給一個"},
    "take_profit": {"type": "number", "description": "停利價（絕對價格）"},
    "reason": {"type": "string", "description": "設定當下的討論結論——保留歷史的意義所在，強烈建議填"}
  },
  "required": ["code"]
}
```

回傳：`{"saved": true, "id": 12, "code": "2337", "stop_loss": 110.0,
"take_profit": null, "reason": "...", "created_at": "..."}`

**驗證**（違反則回錯誤，不寫入）：兩個門檻皆空、值不可轉 float 或 <= 0、
兩者都給但 `stop_loss >= take_profit`。

**append-only**：重新設定同一檔會新增一筆，舊值保留供追溯（FR-001）。

### `get_exit_threshold`（唯讀工具）

```json
{
  "type": "object",
  "properties": {
    "code": {"type": "string", "description": "台股代碼；省略＝回傳全部持股的門檻與觸發狀態"},
    "include_history": {"type": "boolean", "description": "是否一併回傳該檔的設定歷史（預設 false）"}
  }
}
```

單檔回傳：

```json
{
  "code": "2337",
  "status": "within_range",
  "stop_loss": 110.0,
  "take_profit": 160.0,
  "current_price": 126.0,
  "price_date": "2026-08-31",
  "distance_pct": -12.7,
  "reason": "跌破月線且營收轉弱就出場",
  "set_at": "2026-09-03T10:00:00",
  "history": []
}
```

全部模式：`{"count": N, "positions": [...], "summary": {"not_set": 12,
"within_range": 5, "triggered_stop_loss": 1, "triggered_take_profit": 1,
"no_price": 0}}`

**status 值域**：`not_set`／`no_price`／`triggered_stop_loss`／
`triggered_take_profit`／`within_range`。

**關鍵約束**：`not_set` MUST NOT 被呈現為 `within_range` 或任何安全語意
（FR-003）；`stop_loss`／`take_profit` 在未設定時 MUST 為 null，不得填
任何預設值。

## 註冊位置

| # | 檔案 | 內容 |
|---|---|---|
| 1 | `server.py` `TOOLS` | 兩個工具的定義 |
| 2 | `server.py` dispatch | 兩個分支 |
| 3 | `server_readonly.py` `READONLY_TOOLS` | **只加 `get_exit_threshold`**；`save_exit_threshold` 是寫入工具，不得加入（FR-004） |

工具總數：45 → **47**；唯讀白名單：27 → **28**。
階段A 已建立的守門測試（`tests/test_pnl.py::ToolRegistrationTest`）要
擴充涵蓋新工具，並**新增一個反向斷言**：`save_exit_threshold`
**不得**出現在 `READONLY_TOOLS`。

## 既有 API 的回傳結構變更（FR-014／FR-015）

### `GET /api/stocks/{code}` 的 `holdings` 區塊

現況（`app/routers/stock_detail.py:188-206`）只有 `avg_cost`／`pnl_pct`
兩個欄位，語意是「全部買進加權平均、不扣賣出」。新增欄位並存：

| 欄位 | 說明 | 變更 |
|---|---|---|
| `avg_cost`／`pnl_pct` | 既有加權平均估算 | **維持不變**（向後相容） |
| `cost_method_label` | 既有估算的口徑標籤，固定「加權平均估算・未扣賣出・非 FIFO」 | 新增 |
| `fifo` | 階段A `get_position_pnl` 的完整結果（含 `status`／`realized_pnl`／`unrealized_pnl`／`shortfall_shares`） | 新增 |

**前端呈現規則**（`web/src/pages/StockDetail.jsx:299` 附近）：
- `fifo.status == "ok"` → 以 FIFO 數字為主，標註 `FIFO・未扣交易成本`；
  既有估算值收在次要位置
- `fifo.status == "history_incomplete"` → 顯示「FIFO 無法計算：歷史不完整
  （缺口 N 股）」，並顯示既有估算值＋其口徑標籤
- 兩者 MUST 視覺上可區分（FR-015）

### 每日流程的訊號輸出

不新增端點——新訊號以既有 `module_d_results` 的列出現，`trigger_label`
新增 `通用層／停損停利`、`通用層／背離` 兩值。首頁「今日重點」與詳情頁
Checks 卡因既有篩選邏輯（`suggested_action is not None`）自動顯示，
**零前端改動**。

## 明確不在本階段的介面

- **不新增網頁設定表單**（FR-004，PO 裁決 Q3-A）——`app/routers/actions.py`
  不加 `/threshold` 端點
- 不新增任何寫入 `stances` 的路徑（FR-013）
- 不新增自動下單或委託相關介面
