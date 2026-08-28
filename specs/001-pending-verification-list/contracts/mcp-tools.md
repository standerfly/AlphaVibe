# Contract: MCP Tools（`poc/kb-mcp/server.py`）

本 repo 的 MCP server 是純標準庫 stdio JSON-RPC 實作（見
`server.py` 檔案開頭 docstring），工具合約以 `TOOLS` 清單中的
`inputSchema`（JSON Schema）表示，比照既有 `save_stance`／`get_stance`
等工具的寫法。以下是本功能新增的 4 個工具，供 `/speckit.tasks` 拆解
實作任務、以及後續實作時直接參考。

## `save_pending_verification`

登記一筆待觀察項目（對應 FR-001／FR-002，資料模型見 `../data-model.md`）。

```json
{
  "name": "save_pending_verification",
  "description": "登記一筆帶觸發條件與預期時間點的待驗證判斷（FR-001）。缺必填欄位時拒絕寫入並回傳明確錯誤（FR-002）。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "judgment_text": {"type": "string", "description": "判斷/假設內容"},
      "trigger_type": {"type": "string", "enum": ["date", "event"], "description": "觸發類型"},
      "trigger_date": {"type": "string", "description": "YYYY-MM-DD，trigger_type=date 時必填"},
      "trigger_condition_text": {"type": "string", "description": "觸發條件文字描述"},
      "code": {"type": "string", "description": "可選，關聯股票代碼"},
      "theme": {"type": "string", "description": "可選，關聯主題"},
      "target_value": {"type": "string", "description": "可選，具體驗證目標，如「毛利率75%」"},
      "source_ref": {"type": "string", "description": "來源引用"}
    },
    "required": ["judgment_text", "trigger_type", "trigger_condition_text"]
  }
}
```

**行為**：`trigger_type=date` 卻缺 `trigger_date` 時，比照缺必填欄位
處理，拒絕寫入（見 spec.md Edge Cases／FR-001 附帶條件）。回傳新建
記錄的完整內容（含 `id`、`status=pending`、`created_at`）。

## `list_pending_verifications`

查詢待觀察項目清單（對應 FR-003／FR-004）。

```json
{
  "name": "list_pending_verifications",
  "description": "查詢待觀察項目清單，可依狀態篩選，或只列出已到期/即將到期的pending項目（FR-003/FR-004）。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "status": {"type": "string", "enum": ["pending", "resolved", "dropped"], "description": "可選，依狀態篩選；不填則回傳全部狀態"},
      "due_only": {"type": "boolean", "description": "可選，true 時只回傳已到期/即將到期（7天窗口）且status=pending的項目"}
    },
    "required": []
  }
}
```

## `get_pending_verification`

取得單筆待觀察項目完整內容。

```json
{
  "name": "get_pending_verification",
  "description": "取得單筆待觀察項目的完整內容（含歷史resolution/resolved_at，若已標記過）。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "id": {"type": "integer", "description": "待觀察項目ID"}
    },
    "required": ["id"]
  }
}
```

## `resolve_pending_verification`

標記一筆待觀察項目為已驗證或不再追蹤（對應 FR-005／FR-006／FR-007）。

```json
{
  "name": "resolve_pending_verification",
  "description": "標記待觀察項目為resolved（需附resolution）或dropped（resolution可選）。已是終態的項目不可再次轉換（FR-007）。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "id": {"type": "integer", "description": "待觀察項目ID"},
      "status": {"type": "string", "enum": ["resolved", "dropped"], "description": "目標狀態"},
      "resolution": {"type": "string", "description": "status=resolved時必填；status=dropped時可選"}
    },
    "required": ["id", "status"]
  }
}
```

**錯誤情境**：
- `status=resolved` 卻缺 `resolution` → 拒絕，回傳明確錯誤（FR-005／
  spec.md User Story 3 Acceptance Scenario 2）
- 對已是 `resolved`／`dropped` 的項目再次呼叫 → 拒絕（終態不可逆，
  FR-007），錯誤訊息應說明目前狀態並建議登記新項目
- `id` 不存在 → 拒絕，回傳「找不到」類錯誤（比照既有 `app/routers/
  assets.py` 的 404 分類慣例，但 MCP tool 層級直接回傳錯誤訊息文字，
  非 HTTP 狀態碼）
