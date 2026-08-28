# Contract: HTTP API（`app/routers/pending_verifications.py`）

新 router，比照 `app/routers/assets.py` 的風格（Pydantic request model、
`_raise_from_value_error()`-style 錯誤轉換、直接呼叫 `poc/kb-mcp/
kb_store.py` 對應方法，不在 router 重寫商業邏輯）。本功能的 HTTP API
**只服務 STND 首頁的唯讀顯示需求**（FR-008、Q-003a）——登記與標記解決
一律走 MCP tool（見 `mcp-tools.md`），不透過這個 HTTP API 進行寫入
操作也是合理的最小範圍；但為了讓前端能顯示，仍需要一支查詢用的 GET
endpoint。

## `GET /api/pending-verifications`

供 `web/src/pages/Home.jsx` 新增的區塊呼叫，取得「已到期／即將到期」
的待驗證項目清單。

**Query Parameters**：
- `due_only`（bool，可選，預設 `true`）：是否只回傳已到期/即將到期
  （7天窗口，見 `../research.md` 決策5）且 `status=pending` 的項目
- `status`（string，可選）：依狀態篩選；與 `due_only=true` 併用時，
  `status` 會被忽略（`due_only` 語意本身已限定 `status=pending`）

**Response 200**：
```json
{
  "items": [
    {
      "id": 1,
      "code": "2330",
      "theme": null,
      "judgment_text": "...",
      "trigger_type": "date",
      "trigger_date": "2026-08-26",
      "trigger_condition_text": "...",
      "target_value": "毛利率75%",
      "status": "pending",
      "source_ref": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

**Response 200（空清單）**：`{"items": []}`——沒有已到期項目是正常
情況，不是錯誤（首頁區塊應顯示「目前沒有待驗證項目」之類的空狀態，
而非把空陣列當錯誤處理）。

**錯誤情境**：資料庫查詢失敗時回傳 5xx，前端比照 spec.md Acceptance
Scenario（User Story 2 第3點）優雅降級——顯示簡短錯誤提示，不擋首頁
其他區塊。

## 範圍說明：為何不做 POST／PATCH endpoint

登記（`save`）與標記解決（`resolve`）功能已透過 MCP tool 提供（見
`mcp-tools.md`），且 Q-003a 已明確排除首頁就地操作 UI——因此本功能的
HTTP API 只需要一支 GET endpoint 供首頁顯示使用，不需要對應的
POST/PATCH endpoint。若未來範圍擴大（例如真的要做管理頁面），屆時
再依當時的新 pre-spec 決策擴充，不在本次範圍內預先建立。
