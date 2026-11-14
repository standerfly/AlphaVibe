# Contract: MCP 唯讀工具（台股與美股連接器各一份、同一個 articles.db）

註冊位置：`poc/kb-mcp/server.py`（TOOLS＋call_tool）、`poc/kb-mcp/us_stock_mcp_server.py`（TOOLS＋call_tool）、
`poc/kb-mcp/server_readonly.py`（READONLY_TOOLS＋READONLY_TOOL_SCHEMAS）。兩個 Server 的行為與輸出必須逐字相同
（US3 驗收情境 3）。工具名與台股既有工具不得衝突。

## `search_articles`
- 輸入：`query`（string，必填；空白分隔多關鍵字，**全部需出現**）、`limit`（int，預設 10，最大 30）。
- 搜尋範圍：標題＋全文＋圖片轉寫文字；僅 `status='fetched'` 的文章。
- 輸出（文字）：每筆 `標題｜發布日期｜原文網址｜片段（命中處前後約 60 字，標明命中來源：內文／表格轉寫）｜article_id`；
  依發布日期新到舊。無命中 → 明確回「查無符合的文章」，不回無關內容。
- 唯讀；不觸發任何網站存取。

## `get_article`
- 輸入：`article_id`（int，必填）。
- 輸出：標題、發布日期、原文網址、全文；之後列出圖片：`#seq｜是否表格｜轉寫狀態｜本機檔路徑`，表格轉寫文字
  附在該圖下並保留「【機器轉寫，可能有誤】」標示；`untranscribed` 明寫「未轉寫」。找不到或非 `fetched` →
  明確錯誤訊息（不回殘缺內容）。
- 不存在於庫＝不去網站抓（唯讀、不登入）。

## 守門測試同步
- `test_pnl.py::test_tool_counts`：`len(server.TOOLS)` 48→50、`len(READONLY_TOOLS)` 29→31；
- `test_claude_ai_connector.py`：美股 names==TOOLS 的預期清單加兩項；
- 新增：兩個 Server 對同一個測試庫、同一關鍵字回傳完全相同結果的測試；
- Mac 上 `~/.claude` stock-researcher 白名單（不在 repo）由 PO 手動加入，列入上線 checklist。
