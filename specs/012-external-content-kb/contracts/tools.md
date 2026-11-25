# 契約：MCP 工具（7 個）

**Feature**: 012-external-content-kb | **Date**: 2026-11-25
共用規則：
- 所有輸出（含錯誤以外的每一條成功路徑）一律附固定標註：`作者個人觀點，未經查證`；標註由輸出層加上，呼叫端不可省略（FR-003）。**搜尋結果每一個命中項各自附一行標註**（不只在末尾），使單筆被複製引用時不會脫離標註；測試逐筆斷言。
- 輸出為純文字字串（比照 `article_tools.py:131-176`）。錯誤回 `isError`，訊息繁體中文、指出原因。
- 工具名稱不含 `article`、`verif`、`reviewed`（避開既有守門測試）。
- data dir 由伺服器端決定（`ALPHAVIBE_DATA_DIR`／`app/deps.py` 的 `_resolve_data_dir`），工具不接受路徑參數以外的 data dir 設定。
- 掛載：查詢 2 個→`server.py`、`server_readonly.py`、`us_stock_mcp_server.py`；寫入 5 個→只 `server.py`。

## 查詢（唯讀，台美兩端皆有）

### `search_external_content`
搜尋全文。2 字中文詞必須可查到。
- 輸入：`query`（必填，空白切詞 AND）、`source_type`（選填，三值）、`limit`（預設 10、上限 30）。
- 輸出：每筆 `id`、`source_type`、標題、作者、日期、連結、命中片段（半徑 60 字，最多 2 段）、已確認摘要的數量與其 `summary_id` 清單；**每筆各附標註**，末尾再附一次。不回整份全文。
- 無命中：回「沒有找到」＋固定標註。

### `get_external_content`
取單筆。
- 輸入：`id`（必填）、`offset`（選填，字元起點，預設 0）、`length`（選填，字元數；省略＝到結尾全部）、`summary_only`（選填，預設 false；true＝只回中繼資料與已確認摘要，不回原文，供 agent「先看摘要」）、`include_summaries`（選填，預設 true）。
- 輸出：完整中繼資料、`已確認摘要`（每則附 `summary_id`，與原文分段標示）、全文或指定範圍（回報總字數與本次範圍）；固定標註。
- 找不到 ID：錯誤。

## 寫入（只在 `server.py`）

### `create_inbox_file`
建立待匯入檔案（FR-018）。
- 輸入：`url`（必填）、`source_type`（選填，YouTube 連結可自動判斷）、`title`、`author`、`date`（皆選填，作為 agent 已向 PO 取得的值）、`guid`（選填）。
- 流程：算 `source_key`（以網址主機判斷，見 inbox-file-format「身分規則」）→ 已存在則回「已存在」＋既有內容摘要資訊，**不建檔**；否則 YouTube 先盡力自動填缺欄位（R5，含 SSRF 防護）；若仍缺任何必填欄位，回「缺欄位清單」，**不建檔**，agent 須問 PO 補齊後重呼叫；齊全則在 `<data_dir>/inbox/`（最上層，非 processed）建檔（內文留空）並回檔案完整路徑。
- 保證：只在 inbox 內建檔；檔名衝突不覆蓋（加序號）；寫入失敗回錯誤原因、不留半檔。

### `import_inbox`
匯入資料匣內待處理檔案（FR-004）。
- 輸入：`on_duplicate`（選填：`ask`〔預設〕｜`replace`｜`skip`）、`filenames`（選填，限定檔名；**只接受 basename，且必須是 inbox 最上層的檔案**，含路徑分隔字元或指向 `processed/` 者拒絕）。
- 處理順序（每檔獨立交易）：解析中繼資料區塊 → 算 `source_key` → **先判斷是否重複（只看區塊，不驗內文）** → 非重複才驗內文非空、算雜湊、入庫。
  - 非重複：驗證通過即入庫並搬到 processed；失敗則維持待處理。`on_duplicate` 對非重複檔無影響（`skip`／`replace` 都只作用於重複檔，非重複檔仍正常入庫）。
  - 重複：若檔案內文雜湊與庫內該筆相同 → 回 `already_processed` 並搬到 processed（服務端讀檔不經模型，不耗 token）；否則 `ask` 回 `duplicate` 並保留檔案待 PO 決定；`replace` 取代全文（內文須非空，否則 `failed`「內文為空」；保留已確認摘要）並搬到 processed；`skip` 視為 PO 放棄並搬到 processed。
  - **`replace`／`skip` 必須搭配明確的 `filenames`**（避免 PO 只想取代一筆卻波及全部）；省略 `filenames` 又指定這兩值 → 拒絕並說明。
  - 只掃描 inbox 最上層、副檔名 `.md`／`.txt`；其他副檔名（例如 TextEdit 預設的 `.rtf`）**不默默忽略**，列在結果的 `skipped_unsupported` 並提示改存為純文字／Markdown。
- 輸出：逐檔狀態（見 inbox-file-format.md「結果回報」）、成功筆數統計、`skipped_unsupported`；inbox 沒有任何待處理檔時回「資料匣沒有待匯入檔案」。
- 說明（寫在工具描述）：匯入完成後 agent 應附下一步提示並逐檔提出摘要草稿，草稿不得入庫（FR-017）。

### `import_text`
短文備援（FR-005）。
- 輸入：`source_type`、`url`、`title`、`author`、`date`、`body`（皆必填）、`guid`（選填）、`on_duplicate`（選填：`ask`〔預設〕｜`replace`｜`skip`）。
- 重複時的語意（無檔案、無 `filenames`）：`ask` 回 `duplicate`（附既有內容 ID 與標題）、不寫入；`replace` 直接取代該筆全文（保留已確認摘要，寫 `replace` 稽核）；`skip` 不寫入並回報「已放棄」。「`replace`／`skip` 必須搭配 `filenames`」的限制**只適用 `import_inbox`**。內文雜湊與庫內相同時回 `already_processed`（不寫入）。
- 工具描述須標明：此路徑全文經模型輸出，耗 token；長文請走資料匣。
- 限制：`body` 超過上限（預設 200,000 字）→ 「內容過長，請改走資料匣」、不入庫。
- 其餘規則（必填檢查、去重、標註、全有或全無）與 `import_inbox` 相同（共用核心）。

### `confirm_summary`
把 PO **已明確同意**的摘要存入（FR-011/012）。
- 輸入：`content_id`、`action`（`confirm`｜`revise`｜`revoke`）、`text`（`confirm`、`revise` 必填）、`summary_id`（`revise`、`revoke` 必填；可由 `search_external_content`／`get_external_content` 的輸出取得）、`po_confirmed`（`confirm`、`revise` 時必須為 true）、`po_confirmation_quote`（`confirm`、`revise` 時必填，PO 同意的原話）。
- `revise` 在**同一交易**內撤回舊則並新增新則（視同重新確認，需新的原話）；任一步失敗整筆回滾、舊摘要不受影響。
- 工具描述須寫死：僅在 PO 明確說同意後呼叫；草稿、PO 拒絕、沉默一律不得呼叫。
- 缺 `po_confirmed=true` 或原話為空 → 拒絕並說明須 PO 明確同意（錯誤，不入庫）。
- 稽核：記錄原話與時間（`summary_confirm`／`summary_revise`／`summary_revoke`）。
- 已知限制：系統無法驗證原話真偽，屬遵循度保證（research R7）。

### `delete_content`
刪除單筆內容（FR-013）。
- 輸入：`content_id`、`po_confirmed`（必須為 true）、`po_confirmation_quote`（必填）。
- 行為：同一交易刪除 `content` 與其 `summary`，寫入 `delete` 稽核（detail 含標題與原話，不含全文）。缺確認 → 拒絕。

## 守門測試調整

| 測試 | 調整 |
|---|---|
| `test_pnl.py::test_tool_counts` | `len(server.TOOLS)` 50→57；`len(READONLY_TOOLS)` 31→33 |
| `test_traceability.py::test_tools_list_has_fifty` | 50→57（建議順手更名為不含數字的名稱） |
| `test_us_stock_mcp_server.py`（名稱集合相等） | 加入 `search_external_content`、`get_external_content` |
| `test_article_connectors_parity.py`、`test_article_verification.py` | 不需改；新增斷言：外部內容工具名不含保留字 |
| 新增 `test_external_content_readonly.py` | 唯讀端 `tools/list` 只含 2 個查詢工具；呼叫 5 個寫入工具皆被拒絕 |
| 新增 `test_external_content_tools.py` | 每條成功輸出含標註；**搜尋多筆命中時，每個命中項區塊內各含一次標註（逐筆斷言），末尾另有一次**；`confirm_summary` 缺確認即拒；未確認不寫入；`import_text` 的 `ask`／`replace`／`skip`／相同雜湊各路徑 |
| `server_readonly.py:6、:9` | 註解中的數字同步 |
